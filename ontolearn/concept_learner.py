import logging
import time
from contextlib import contextmanager
from itertools import islice
from typing import Iterable, Optional, Dict

import pandas as pd

from ontolearn.search import HeuristicOrderedNode, OENode, TreeNode, LengthOrderedNode, LBLNode, LBLSearchTree, \
    QualityOrderedNode
from owlapy.model import OWLClassExpression
from owlapy.render import DLSyntaxObjectRenderer
from sortedcontainers import SortedSet
from . import KnowledgeBase
from .abstracts import AbstractScorer, BaseRefinement, AbstractHeuristic, AbstractLearningProblem
from .base_concept_learner import BaseConceptLearner
from .core.owl.utils import EvaluatedDescriptionSet, ConceptOperandSorter
from owlapy.util import OrderedOWLObject
from .heuristics import CELOEHeuristic, OCELHeuristic
from .learning_problem import PosNegLPStandard, EncodedPosNegLPStandard
from .metrics import F1
from .refinement_operators import LengthBasedRefinement
from .search import SearchTreePriorityQueue
from .utils import oplogging
from abc import ABCMeta
from .concept_learner import BaseConceptLearner
from .abstracts import AbstractDrill, AbstractScorer
from .utils import *
from .search import Node, SearchTreePriorityQueue
from .data_struct import PrepareBatchOfTraining, PrepareBatchOfPrediction, Experience
from .refinement_operators import LengthBasedRefinement
from .metrics import F1
from .heuristics import Reward
import time
import json
import random
import torch
from torch import nn
import numpy as np
import functools
from torch.functional import F
from typing import List, Any, Set, Tuple, Iterable, Tuple, Iterable, TypeVar, Generic, ClassVar, Optional, Generator, \
    SupportsFloat
from collections import namedtuple, deque
from torch.nn.init import xavier_normal_
from itertools import chain
import matplotlib.pyplot as plt
from torch.optim.lr_scheduler import ExponentialLR

from owlapy.model import OWLNamedIndividual, OWLClassExpression
from ontolearn.search import HeuristicOrderedNode, OENode, TreeNode, LengthOrderedNode, LBLNode, LBLSearchTree, \
    QualityOrderedNode, RL_State
from ontolearn.abstracts import AbstractNode

pd.set_option('display.max_columns', 100)

logger = logging.getLogger(__name__)

_concept_operand_sorter = ConceptOperandSorter()


class CELOE(BaseConceptLearner[OENode]):
    __slots__ = 'best_descriptions', 'max_he', 'min_he', 'best_only', 'calculate_min_max', 'heuristic_queue', \
                'search_tree', '_learning_problem', '_max_runtime'

    name = 'celoe_python'

    kb: KnowledgeBase

    max_he: int
    min_he: int
    best_only: bool
    calculate_min_max: bool

    search_tree: Dict[OWLClassExpression, TreeNode[OENode]]
    heuristic_queue: 'SortedSet[OENode]'
    best_descriptions: EvaluatedDescriptionSet[OENode, QualityOrderedNode]
    _learning_problem: Optional[EncodedPosNegLPStandard]

    def __init__(self,
                 knowledge_base: KnowledgeBase,
                 refinement_operator: Optional[BaseRefinement[OENode]] = None,
                 quality_func: Optional[AbstractScorer] = None,
                 heuristic_func: Optional[AbstractHeuristic] = None,
                 terminate_on_goal: Optional[bool] = None,
                 iter_bound: Optional[int] = None,
                 max_num_of_concepts_tested: Optional[int] = None,
                 max_runtime: Optional[int] = None,
                 max_results: int = 10,
                 best_only: bool = False,
                 calculate_min_max: bool = True):
        super().__init__(knowledge_base=knowledge_base,
                         refinement_operator=refinement_operator,
                         quality_func=quality_func,
                         heuristic_func=heuristic_func,
                         terminate_on_goal=terminate_on_goal,
                         iter_bound=iter_bound,
                         max_num_of_concepts_tested=max_num_of_concepts_tested,
                         max_runtime=max_runtime)

        self.search_tree = dict()
        self.heuristic_queue = SortedSet(key=HeuristicOrderedNode)
        self.best_descriptions = EvaluatedDescriptionSet(max_size=max_results, ordering=QualityOrderedNode)

        self.best_only = best_only
        self.calculate_min_max = calculate_min_max

        self.max_he = 0
        self.min_he = 1
        # TODO: CD: This could be defined in BaseConceptLearner as it is used in all classes that inherits from BaseConceptLearner
        self._learning_problem = None
        self._max_runtime = None

    def next_node_to_expand(self, step: int) -> OENode:
        if not self.best_only:
            for node in reversed(self.heuristic_queue):
                if node.quality < 1.0:
                    return node
            else:
                raise ValueError("No Node with lesser accuracy found")
        else:
            # from reimplementation, pick without quality criterion
            return self.heuristic_queue[-1]

        # Original reimplementation of CELOE: Sort search tree at each step. Quite inefficient.
        # self.search_tree.sort_search_tree_by_decreasing_order(key='heuristic')
        # if self.verbose > 1:
        #     self.search_tree.show_search_tree(step)
        # for n in self.search_tree:
        #     return n
        # raise ValueError('Search Tree can not be empty.')

    def best_hypotheses(self, n=10) -> Iterable[OENode]:
        yield from islice(self.best_descriptions, n)

    def make_node(self, c: OWLClassExpression, parent_node: Optional[OENode] = None, is_root: bool = False) -> OENode:
        r = OENode(c, self.kb.cl(c), parent_node=parent_node, is_root=is_root)
        return r

    @contextmanager
    def updating_node(self, node: OENode):
        self.heuristic_queue.discard(node)
        yield node
        self.heuristic_queue.add(node)

    def downward_refinement(self, node: OENode) -> Iterable[OENode]:
        assert isinstance(node, OENode)

        with self.updating_node(node):
            # TODO: NNF
            refinements = SortedSet(
                map(_concept_operand_sorter.sort,
                    self.operator.refine(
                        node.concept,
                        max_length=node.h_exp,
                        current_domain=self.start_class)
                    )  # noqa: E203
                ,
                key=OrderedOWLObject)

            node.increment_h_exp()
            node.refinement_count = len(refinements)
            self.heuristic_func.apply(node, None, self._learning_problem)

        def make_node_with_parent(c: OWLClassExpression):
            return self.make_node(c, parent_node=node)

        return map(make_node_with_parent, refinements)

    def fit(self, learning_problem: PosNegLPStandard,
            max_runtime: Optional[int] = None):
        """
        Find hypotheses that explain pos and neg.
        """
        self.clean()
        assert not self.search_tree
        assert isinstance(learning_problem, PosNegLPStandard)
        self._learning_problem = learning_problem.encode_kb(self.kb)

        if max_runtime is not None:
            self._max_runtime = max_runtime
        else:
            self._max_runtime = self.max_runtime
        root = self.make_node(_concept_operand_sorter.sort(self.start_class), is_root=True)
        self._add_node(root, None)
        assert len(self.heuristic_queue) == 1
        # TODO:CD:suggest to add another assert,e.g. assert #. of instance in root > 1

        self.start_time = time.time()
        for j in range(1, self.iter_bound):
            most_promising = self.next_node_to_expand(j)
            tree_parent = self.node_tree_parent(most_promising)
            minimum_length = most_promising.h_exp
            if logger.isEnabledFor(oplogging.TRACE):
                logger.debug("now refining %s", most_promising)
            for ref in self.downward_refinement(most_promising):
                # we ignore all refinements with lower length
                # (this also avoids duplicate node children)
                # TODO: ignore too high depth
                if ref.len < minimum_length:
                    # ignoring refinement, it does not satisfy minimum_length condition
                    continue

                # note: tree_parent has to be equal to node_tree_parent(ref.parent_node)!
                added = self._add_node(ref, tree_parent)

                goal_found = added and ref.quality == 1.0

                if goal_found and self.terminate_on_goal:
                    return self.terminate()

            if self.calculate_min_max:
                # This is purely a statistical function, it does not influence CELOE
                self.update_min_max_horiz_exp(most_promising)

            if time.time() - self.start_time > self._max_runtime:
                return self.terminate()

            if self.number_of_tested_concepts >= self.max_num_of_concepts_tested:
                return self.terminate()

        return self.terminate()

    def node_tree_parent(self, node: OENode) -> TreeNode[OENode]:
        tree_parent = self.search_tree[node.concept]
        return tree_parent

    def _add_node(self, ref: OENode, tree_parent: Optional[TreeNode[OENode]]):
        # TODO:CD: Why have this constraint ?
        #  We should not ignore a concept due to this constraint.
        #  It might be the case that new path to ref.concept is a better path. Hence, we should update its parent depending on the new heuristic value.
        #  Solution: If concept exists we should compare its first heuristic value  with the new one
        if ref.concept in self.search_tree:
            # ignoring refinement, it has been refined from another parent
            return False
        self.search_tree[ref.concept] = TreeNode(ref, tree_parent, is_root=ref.is_root)
        ref_individuals = self.kb.individuals_set(ref.concept)
        ref.individuals_count = len(ref_individuals)
        self.quality_func.apply(ref, ref_individuals, self._learning_problem)  # AccuracyOrTooWeak(n)
        self._number_of_tested_concepts += 1
        if ref.quality == 0:  # > too weak
            return False
        assert 0 <= ref.quality <= 1.0
        # TODO: expression rewriting
        self.heuristic_func.apply(ref, ref_individuals, self._learning_problem)
        if self.best_descriptions.maybe_add(ref):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Better description found: %s", ref)
        self.heuristic_queue.add(ref)
        # TODO: implement noise
        return True

    def show_search_tree(self, heading_step: str, top_n: int = 10) -> None:
        """
        Show search tree.
        """
        rdr = DLSyntaxObjectRenderer()

        print('######## ', heading_step, 'step Search Tree ###########')

        def tree_node_as_length_ordered_concept(tn: TreeNode[OENode]):
            return LengthOrderedNode(tn.node, tn.node.len)

        def print_partial_tree_recursive(tn: TreeNode[OENode], depth: int = 0):
            if tn.node.heuristic is not None:
                heur_idx = len(self.heuristic_queue) - self.heuristic_queue.index(tn.node)
            else:
                heur_idx = None

            if tn.node in self.best_descriptions:
                best_idx = len(self.best_descriptions.items) - self.best_descriptions.items.index(tn.node)
            else:
                best_idx = None

            render_str = rdr.render(tn.node.concept)

            depths = "`" * depth

            if best_idx is not None or heur_idx is not None:
                if best_idx is None:
                    best_idx = ""
                if heur_idx is None:
                    heur_idx = ""

                print("[%3s] [%4s] %s %s \t HE:%s Q:%f Heur:%s |RC|:%s" % (best_idx, heur_idx, depths, render_str,
                                                                           tn.node.h_exp, tn.node.quality,
                                                                           tn.node.heuristic, tn.node.refinement_count))

            for c in sorted(tn.children, key=tree_node_as_length_ordered_concept):
                print_partial_tree_recursive(c, depth + 1)

        print_partial_tree_recursive(self.search_tree[self.start_class])

        print('######## ', heading_step, 'step Best Hypotheses ###########')

        predictions = list(self.best_hypotheses(top_n))
        for ith, node in enumerate(predictions):
            print('{0}-\t{1}\t{2}:{3}\tHeuristic:{4}:'.format(ith + 1, rdr.render(node.concept),
                                                              type(self.quality_func).name, node.quality,
                                                              node.heuristic))
        print('######## Search Tree ###########\n')

    def update_min_max_horiz_exp(self, node: OENode):
        he = node.h_exp
        # update maximum value
        self.max_he = max(self.max_he, he)

        if self.min_he == he - 1:
            threshold_score = node.heuristic + 1 - node.quality

            for n in reversed(self.heuristic_queue):
                if n == node:
                    continue
                if n.h_exp == self.min_he:
                    """ we can stop instantly when another node with min. """
                    return
                if n.heuristic < threshold_score:
                    """ we can stop traversing nodes when their score is too low. """
                    break
            # inc. minimum since we found no other node which also has min. horiz. exp.
            self.min_he += 1

            if logger.isEnabledFor(oplogging.TRACE):
                logger.info("minimum horizontal expansion is now %d", self.min_he)

    def clean(self):
        self.heuristic_queue.clear()
        self.best_descriptions.clean()
        self.search_tree.clear()
        self.max_he = 0
        self.min_he = 1
        self._learning_problem = None
        self._max_runtime = None
        super().clean()


class OCEL(CELOE):
    __slots__ = ()

    name = 'ocel_python'

    def __init__(self, knowledge_base, quality_func=None, iter_bound=None, max_num_of_concepts_tested=None,
                 terminate_on_goal=None):
        super().__init__(knowledge_base=knowledge_base,
                         quality_func=quality_func,
                         heuristic_func=OCELHeuristic(),
                         terminate_on_goal=terminate_on_goal,
                         iter_bound=iter_bound, max_num_of_concepts_tested=max_num_of_concepts_tested)


class Drill(AbstractDrill, BaseConceptLearner):
    search_tree: Dict[OWLClassExpression, TreeNode[OENode]]
    heuristic_queue: 'SortedSet[OENode]'

    def __init__(self, knowledge_base,
                 path_of_embeddings=None,
                 drill_first_out_channels=32,
                 refinement_operator=None, quality_func=None, gamma=None,
                 pretrained_model_path=None, iter_bound=None, max_num_of_concepts_tested=None, verbose=None,
                 terminate_on_goal=True, ignored_concepts=None,
                 max_len_replay_memory=None, batch_size=None, epsilon_decay=None, epsilon_min=None,
                 num_epochs_per_replay=None, num_episodes_per_replay=None, learning_rate=None, relearn_ratio=None,
                 max_results: int = 10, best_only: bool = False, calculate_min_max: bool = True,
                 max_runtime=None, num_of_sequential_actions=None, num_episode=None, num_workers=32):
        AbstractDrill.__init__(self,
                               path_of_embeddings=path_of_embeddings,
                               reward_func=Reward(),
                               max_len_replay_memory=max_len_replay_memory,
                               batch_size=batch_size, epsilon_min=epsilon_min,
                               num_epochs_per_replay=num_epochs_per_replay,
                               representation_mode='averaging',
                               epsilon_decay=epsilon_decay,
                               num_of_sequential_actions=num_of_sequential_actions, num_episode=num_episode,
                               learning_rate=learning_rate,
                               num_workers=num_workers)
        self.sample_size = 1
        arg_net = {'input_shape': (4 * self.sample_size, self.embedding_dim),
                   'first_out_channels': 32, 'second_out_channels': 16, 'third_out_channels': 8,
                   'kernel_size': 3}
        self.heuristic_func = DrillHeuristic(mode='averaging', model_args=arg_net)
        self.optimizer = torch.optim.Adam(self.heuristic_func.net.parameters(), lr=self.learning_rate)

        if pretrained_model_path:
            m = torch.load(pretrained_model_path, torch.device('cpu'))
            self.heuristic_func.net.load_state_dict(m)

        BaseConceptLearner.__init__(self, knowledge_base=knowledge_base,
                                    refinement_operator=refinement_operator,
                                    quality_func=quality_func,
                                    heuristic_func=self.heuristic_func,
                                    terminate_on_goal=terminate_on_goal,
                                    iter_bound=iter_bound,
                                    max_num_of_concepts_tested=max_num_of_concepts_tested,
                                    max_runtime=max_runtime)
        print('Number of parameters: ', sum([p.numel() for p in self.heuristic_func.net.parameters()]))

        self.search_tree = dict()
        self.heuristic_queue = SortedSet(key=HeuristicOrderedNode)
        self.best_descriptions = EvaluatedDescriptionSet(max_size=max_results, ordering=QualityOrderedNode)

        self.best_only = best_only
        self.calculate_min_max = calculate_min_max
        self._learning_problem = None

        self.max_he = 0
        self.min_he = 1

    def best_hypotheses(self, n=10) -> Iterable:
        ValueError('best_hypotheses')

    def clean(self):
        ValueError('clean')

    def downward_refinement(self, *args, **kwargs):
        ValueError('downward_refinement')

    def fit(self, *args, **kwargs):
        ValueError('fit')

    def show_search_tree(self, heading_step: str, top_n: int = 10) -> None:
        ValueError('show_search_tree')

    def terminate_training(self):
        ValueError('terminate_training')

    def init_training(self, pos_uri: Set[OWLNamedIndividual], neg_uri: Set[OWLNamedIndividual]) -> None:
        """
        Initialize training.


        @return:
        """
        # 1.
        # Generate a Learning Problem
        self._learning_problem = PosNegLPStandard(pos=pos_uri, neg=neg_uri).encode_kb(self.kb)
        # Update REWARD FUNC FOR each learning problem
        self.reward_func.lp = self._learning_problem

        # 2. Obtain embeddings of positive and negative examples.
        self.emb_pos = torch.tensor(
            self.instance_embeddings.loc[[owl_indv.get_iri().as_str() for owl_indv in pos_uri]].values,
            dtype=torch.float32)
        self.emb_neg = torch.tensor(
            self.instance_embeddings.loc[[owl_indv.get_iri().as_str() for owl_indv in neg_uri]].values,
            dtype=torch.float32)

        # (3) Take the mean of positive and negative examples and reshape it into (1,1,embedding_dim) for mini batching.
        self.emb_pos = torch.mean(self.emb_pos, dim=0)
        self.emb_pos = self.emb_pos.view(1, 1, self.emb_pos.shape[0])
        self.emb_neg = torch.mean(self.emb_neg, dim=0)
        self.emb_neg = self.emb_neg.view(1, 1, self.emb_neg.shape[0])
        # Sanity checking
        if torch.isnan(self.emb_pos).any() or torch.isinf(self.emb_pos).any():
            print(string_balanced_pos)
            raise ValueError('invalid value detected in E+,\n{0}'.format(self.emb_pos))
        if torch.isnan(self.emb_neg).any() or torch.isinf(self.emb_neg).any():
            raise ValueError('invalid value detected in E-,\n{0}'.format(self.emb_neg))

        # Default exploration exploitation tradeoff.
        self.epsilon = 1

    def create_rl_state(self, c: OWLClassExpression, parent_state: Optional[RL_State] = None,
                        is_root: bool = False) -> RL_State:
        # Create State
        rl_state = RL_State(c, parent_state=parent_state, is_root=is_root)
        # Assign Embeddings to it. Later, assign_embeddings can be also done in RL_STATE
        self.assign_embeddings(rl_state)
        rl_state.length = self.kb.cl(c)
        return rl_state

    def apply_rho(self, rl_state: RL_State) -> Generator:
        """
        Refine an OWL Class expression \\|= Observing next possible states

        Computation O(N).

        1. Generate concepts by refining a node
        1.1. Compute allowed length of refinements
        1.2. Convert concepts if concepts do not belong to  self.concepts_to_ignore
             Note that          i.str not in self.concepts_to_ignore => O(1) if a set is being used.
        3. Return Generator
        """
        assert isinstance(rl_state, RL_State)
        # 1.
        # (1.1)
        # self.kb.cl(node.concept)
        length = rl_state.length + 3 if rl_state.length + 3 <= self.max_child_length else self.max_child_length
        # (1.2)
        for i in self.operator.refine(rl_state.concept, max_length=length):  # O(N)
            # TODO: CURRENTLY IGNORED the checking not wanted concetpts if i.str not in self.concepts_to_ignore:  # O(1)
            yield self.create_rl_state(i, parent_state=rl_state)  # O(1)

    def rl_learning_loop(self, pos_uri: Set[str], neg_uri: Set[str]) -> List[float]:
        # (1) Initialize
        self.init_training(pos_uri=pos_uri, neg_uri=neg_uri)
        root_rl_state = self.create_rl_state(self.start_class, is_root=True)
        self.quality_func.apply(root_rl_state, root_rl_state.instances_set, self._learning_problem)

        sum_of_rewards_per_actions = []
        log_every_n_episodes = int(self.num_episode * .1) + 1

        # (2)
        for th in range(self.num_episode):
            # (2.1)
            sequence_of_states, rewards = self.sequence_of_actions(root_rl_state)

            if th % log_every_n_episodes == 0:
                print('{0}.th iter. SumOfRewards: {1:.2f}\tEpsilon:{2:.2f}\t|ReplayMem.|:{3}'.format(th, sum(rewards),
                                                                                                     self.epsilon, len(
                        self.experiences)))

            # (2.2)
            self.epsilon -= self.epsilon_decay
            if self.epsilon < self.epsilon_min:
                break

            # (2.3)
            self.form_experiences(sequence_of_states, rewards)

            # (2.4)
            if th % self.num_epochs_per_replay == 0 and len(self.experiences) > 1:
                self.learn_from_replay_memory()
            sum_of_rewards_per_actions.append(sum(rewards))
        return sum_of_rewards_per_actions

    def sequence_of_actions(self, root_rl_state: RL_State) -> Tuple[
        List[Tuple[AbstractNode, AbstractNode]], List[SupportsFloat]]:
        assert isinstance(root_rl_state, RL_State)

        current_state = root_rl_state
        path_of_concepts = []
        rewards = []

        assert len(current_state.embeddings) > 0  # Embeddings are initialized
        assert current_state.quality > 0
        assert current_state.heuristic is None

        # (1)
        for _ in range(self.num_of_sequential_actions):
            assert isinstance(current_state, RL_State)
            # (1.1) Observe Next RL states, i.e., refine an OWL class expression
            next_rl_states = list(self.apply_rho(current_state))

            # (1.2)
            if len(next_rl_states) == 0:  # DEAD END
                assert (current_state.length + 3) <= self.max_child_length
                print('No nexst state')
                break
            # (1.3)
            next_selected_rl_state = self.exploration_exploitation_tradeoff(current_state, next_rl_states)
            print(f'CURRENT:{current_state}')
            print(f'CURRENT:{next_selected_rl_state}')
            exit(1)

            print(next_selected_rl_state)

            if len(next_selected_rl_state.instances) == 0:  # Dead End
                print('BREAK')
                print(next_selected_rl_state)
                break
            # (1.4) Remember the concept path
            path_of_concepts.append((current_state, next_selected_rl_state))

            # (1.5)
            rewards.append(self.reward_func.apply(current_state, next_selected_rl_state))
            # (1.6)
            current_state = next_selected_rl_state
        print('asd')
        exit(1)
        # (2)
        return path_of_concepts, rewards

    def next_node_to_expand(self, t: int = None) -> AbstractNode:
        """
        Return a node that maximizes the heuristic function at time t
        @param t:
        @return:
        """
        if self.verbose > 1:
            self.search_tree.show_search_tree(self.start_class, t)
        return self.search_tree.get_most_promising()

    def form_experiences(self, state_pairs: List, rewards: List) -> None:
        """
        Form experiences from a sequence of concepts and corresponding rewards.

        state_pairs - a list of tuples containing two consecutive states
        reward      - a list of reward.

        Gamma is 1.

        Return
        X - a list of embeddings of current concept, next concept, positive examples, negative examples
        y - argmax Q value.
        """

        for th, consecutive_states in enumerate(state_pairs):
            e, e_next = consecutive_states
            self.experiences.append(
                (e, e_next, max(rewards[th:])))  # given e, e_next, Q val is the max Q value reachable.

    def learn_from_replay_memory(self) -> None:
        """
        Learning by replaying memory
        @return:
        """

        current_state_batch, next_state_batch, q_values = self.experiences.retrieve()
        current_state_batch = torch.cat(current_state_batch, dim=0)
        next_state_batch = torch.cat(next_state_batch, dim=0)
        q_values = torch.Tensor(q_values)

        try:
            assert current_state_batch.shape[1] == next_state_batch.shape[1] == self.emb_pos.shape[1] == \
                   self.emb_neg.shape[1]

        except AssertionError as e:
            print(current_state_batch.shape)
            print(next_state_batch.shape)
            print(self.emb_pos.shape)
            print(self.emb_neg.shape)
            print('Wrong format.')
            print(e)
            raise

        assert current_state_batch.shape[2] == next_state_batch.shape[2] == self.emb_pos.shape[2] == self.emb_neg.shape[
            2]
        dataset = PrepareBatchOfTraining(current_state_batch=current_state_batch,
                                         next_state_batch=next_state_batch,
                                         p=self.emb_pos, n=self.emb_neg, q=q_values)
        num_experience = len(dataset)
        data_loader = torch.utils.data.DataLoader(dataset,
                                                  batch_size=self.batch_size, shuffle=True,
                                                  num_workers=self.num_workers)
        print(f'Number of experiences:{num_experience}')
        print('DQL agent is learning via experience replay')
        self.heuristic_func.net.train()
        for m in range(self.num_epochs_per_replay):
            total_loss = 0
            for X, y in data_loader:
                self.optimizer.zero_grad()  # zero the gradient buffers
                # forward
                predicted_q = self.heuristic_func.net.forward(X)
                # loss
                loss = self.heuristic_func.net.loss(predicted_q, y)
                total_loss += loss.item()
                # compute the derivative of the loss w.r.t. the parameters using backpropagation
                loss.backward()
                # clip gradients if gradients are killed. =>torch.nn.utils.clip_grad_norm_(self.model.parameters(), 0.5)
                self.optimizer.step()
        self.heuristic_func.net.train().eval()

    def update_search(self, concepts, predicted_Q_values):
        """
        @param concepts:
        @param predicted_Q_values:
        @return:
        """
        # simple loop.
        for child_node, pred_Q in zip(concepts, predicted_Q_values):
            child_node.heuristic = pred_Q
            self.search_tree.quality_func.apply(child_node)
            if child_node.quality > 0:  # > too weak, ignore.
                self.search_tree.add(child_node)
            if child_node.quality == 1:
                return child_node

    def assign_embeddings(self, rl_state: RL_State) -> None:
        assert isinstance(rl_state, RL_State)

        # (1) Detect mode
        if self.representation_mode == 'averaging':
            # (2) if input node has not seen before, assign embeddings.
            if rl_state.embeddings is None:
                assert rl_state.instances is None
                assert isinstance(rl_state.concept, OWLClassExpression)
                instances = list(self.kb.individuals(rl_state.concept))
                try:
                    assert len(instances) > 0
                except AssertionError:
                    print(rl_state)
                    print(rl_state.concept)
                    for i in self.kb.individuals(rl_state.concept):
                        print(i)
                    raise

                rl_state.instances = instances
                # BITSET REPRESENTATION
                rl_state.instances_set = self.kb.individuals_set(rl_state.concept)
                str_idx = [i.get_iri().as_str() for i in rl_state.instances]
                if len(str_idx) == 0:
                    emb = torch.zeros(self.sample_size, self.instance_embeddings.shape[1])
                else:
                    emb = torch.tensor(self.instance_embeddings.loc[str_idx].values, dtype=torch.float32)
                    emb = torch.mean(emb, dim=0)
                emb = emb.view(1, self.sample_size, self.instance_embeddings.shape[1])
                rl_state.embeddings = emb
            else:
                """ Embeddings already assigned."""

                try:
                    assert len(rl_state.instances) > 0
                except:
                    print(rl_state)
                    raise

                try:
                    assert rl_state.embeddings.shape == (1, self.sample_size, self.instance_embeddings.shape[1])
                except AssertionError as e:
                    print(e)
                    print(rl_state)
                    print(rl_state.embeddings.shape)
                    print((1, self.sample_size, self.instance_embeddings.shape[1]))
                    raise
        elif self.representation_mode == 'sampling':
            if node.embeddings is None:
                str_idx = [get_full_iri(i).replace('\n', '') for i in node.concept.instances]
                if len(str_idx) >= self.sample_size:
                    sampled_str_idx = random.sample(str_idx, self.sample_size)
                    emb = torch.tensor(self.instance_embeddings.loc[sampled_str_idx].values, dtype=torch.float32)
                else:
                    num_rows_to_fill = self.sample_size - len(str_idx)
                    emb = torch.tensor(self.instance_embeddings.loc[str_idx].values, dtype=torch.float32)
                    emb = torch.cat((torch.zeros(num_rows_to_fill, self.instance_embeddings.shape[1]), emb))
                emb = emb.view(1, self.sample_size, self.instance_embeddings.shape[1])
                node.embeddings = emb
            else:
                """ Embeddings already assigned."""
                try:
                    assert node.embeddings.shape == (1, self.sample_size, self.instance_embeddings.shape[1])
                except AssertionError:
                    print(node)
                    print(self.sample_size)
                    print(node.embeddings.shape)
                    print((1, self.sample_size, self.instance_embeddings.shape[1]))
                    raise ValueError
        else:
            raise ValueError

        # @todo remove this testing in experiments.
        if torch.isnan(rl_state.embeddings).any() or torch.isinf(rl_state.embeddings).any():
            # No individual contained in the input concept.
            # Sanity checking.
            raise ValueError

    def save_weights(self):
        """
        Save pytorch weights.
        @return:
        """
        # Save model.
        torch.save(self.heuristic_func.net.state_dict(),
                   self.storage_path + '/{0}.pth'.format(self.heuristic_func.name))

    def exploration_exploitation_tradeoff(self, current_state: AbstractNode,
                                          next_states: List[AbstractNode]) -> AbstractNode:
        """
        Exploration vs Exploitation tradeoff at finding next state.
        (1) Exploration
        (2) Exploitation
        """
        if np.random.random() < self.epsilon:
            next_state = random.choice(next_states)
            self.assign_embeddings(next_state)
        else:
            next_state = self.exploitation(current_state, next_states)
        self.quality_func.apply(next_state, next_state.instances_set, self._learning_problem)
        return next_state

    def exploitation(self, current_state: AbstractNode, next_states: List[AbstractNode]) -> AbstractNode:
        """
        Find next node that is assigned with highest predicted Q value.

        (1) Predict Q values : predictions.shape => torch.Size([n, 1]) where n = len(next_states)

        (2) Find the index of max value in predictions

        (3) Use the index to obtain next state.

        (4) Return next state.
        """
        predictions: torch.Tensor = self.predict_Q(current_state, next_states)
        argmax_id = int(torch.argmax(predictions))
        next_state = next_states[argmax_id]
        """
        # Sanity checking
        print('#'*10)
        for s, q in zip(next_states, predictions):
            print(s, q)
        print('#'*10)
        print(next_state,f'\t {torch.max(predictions)}')
        """
        return next_state

    def predict_Q(self, current_state: AbstractNode, next_states: List[AbstractNode]) -> torch.Tensor:
        """
        Predict promise of next states given current state.
        @param current_state:
        @param next_states:
        @return: predicted Q values.
        """
        self.assign_embeddings(current_state)
        assert len(next_states) > 0
        with torch.no_grad():
            self.heuristic_func.net.eval()
            # create batch batch.
            next_state_batch = []
            for _ in next_states:
                self.assign_embeddings(_)
                next_state_batch.append(_.embeddings)
            next_state_batch = torch.cat(next_state_batch, dim=0)
            ds = PrepareBatchOfPrediction(current_state.embeddings,
                                          next_state_batch,
                                          self.emb_pos,
                                          self.emb_neg)
            predictions = self.heuristic_func.net.forward(ds.get_all())
        return predictions

    def train(self, dataset: Iterable[Tuple[str, Set, Set]], relearn_ratio: int = 2):
        """
        Train RL agent on learning problems with relearn_ratio.
        @param dataset: An iterable containing training data. Each item corresponds to a tuple of string representation
        of target concept, a set of positive examples in the form of URIs amd a set of negative examples in the form of
        URIs, respectively.
        @param relearn_ratio: An integer indicating the number of times dataset is iterated.

        # @TODO determine Big-O

        Computation
        1. Dataset and relearn_ratio loops: Learn each problem relearn_ratio times,

        2. Learning loop

        3. Take post process action that implemented by subclass.

        @return: self
        """
        # We need a better way of login,
        print('Training starts.')
        print(f'Training starts.\nNumber of learning problem:{len(dataset)},\t Relearn ratio:{relearn_ratio}')
        counter = 1
        # 1.
        for _ in range(relearn_ratio):
            for (alc_concept_str, positives, negatives) in dataset:
                print(
                    'Goal Concept:{0}\tE^+:[{1}] \t E^-:[{2}]'.format(alc_concept_str,
                                                                      len(positives), len(negatives)))
                # 2.
                print(f'RL training on {counter}.th learning problem starts')
                sum_of_rewards_per_actions = self.rl_learning_loop(pos_uri=positives, neg_uri=negatives)

                print(f'Sum of Rewards in first 3 trajectory:{sum_of_rewards_per_actions[:3]}')
                print(f'Sum of Rewards in last 3 trajectory:{sum_of_rewards_per_actions[:3]}')
                self.seen_examples.setdefault(counter, dict()).update(
                    {'Concept': alc_concept_str, 'Positives': list(positives), 'Negatives': list(negatives)})

                counter += 1
                if counter % 100 == 0:
                    self.save_weights()
                # 3.
        return self.terminate_training()


class DrillHeuristic():
    """
    Heuristic in Convolutional DQL concept learning.
    Heuristic implements a convolutional neural network.
    """

    def __init__(self, pos=None, neg=None, model=None, mode=None, model_args=None):
        if model:
            self.net = model
        elif mode in ['averaging', 'sampling']:
            self.net = DrillNet(model_args)
            self.mode = mode
            self.name = 'DrillHeuristic_' + self.mode
        else:
            raise ValueError
        self.net.eval()

    def score(self, node, parent_node=None):
        """ Compute heuristic value of root node only"""
        if parent_node is None and node.is_root:
            return torch.FloatTensor([.0001]).squeeze()
        raise ValueError

    def apply(self, node, parent_node=None):
        """ Assign predicted Q-value to node object."""
        predicted_q_val = self.score(node, parent_node)
        node.heuristic = predicted_q_val


class DrillNet(nn.Module):
    """
    A neural model for Deep Q-Learning.

    An input Drill has the following form
            1. indexes of individuals belonging to current state (s).
            2. indexes of individuals belonging to next state state (s_prime).
            3. indexes of individuals provided as positive examples.
            4. indexes of individuals provided as negative examples.

    Given such input, we from a sparse 3D Tensor where  each slice is a **** N *** by ***D***
    where N is the number of individuals and D is the number of dimension of embeddings.
    Given that N on the current benchmark datasets < 10^3, we can get away with this computation. By doing so
    we do not need to subsample from given inputs.

    """

    def __init__(self, args):
        super(DrillNet, self).__init__()
        self.in_channels, self.embedding_dim = args['input_shape']
        self.loss = nn.MSELoss()

        self.conv1 = nn.Conv2d(in_channels=self.in_channels,
                               out_channels=args['first_out_channels'],
                               kernel_size=args['kernel_size'],
                               padding=1, stride=1, bias=True)

        # Fully connected layers.
        self.size_of_fc1 = int(args['first_out_channels'] * self.embedding_dim)
        self.fc1 = nn.Linear(in_features=self.size_of_fc1, out_features=self.size_of_fc1 // 2)
        self.fc2 = nn.Linear(in_features=self.size_of_fc1 // 2, out_features=1)

        self.init()
        assert self.__sanity_checking(torch.rand(32, 4, 1, self.embedding_dim)).shape == (32, 1)

    def init(self):
        xavier_normal_(self.fc1.weight.data)
        xavier_normal_(self.conv1.weight.data)

    def __sanity_checking(self, X):
        return self.forward(X)

    def forward(self, X: torch.FloatTensor):
        # X denotes a batch of tensors where each tensor has the shape of (4, 1, embedding_dim)
        # 4 => S, S', E^+, E^- \in R^embedding_dim
        # @TODO: Later batch norm and residual learning block.
        X = F.relu(self.conv1(X))
        X = X.view(X.shape[0], X.shape[1] * X.shape[2] * X.shape[3])
        X = F.relu(self.fc1(X))
        return self.fc2(X)


class LengthBaseLearner(BaseConceptLearner):
    """
    CD: An idea for next possible work.
    Propose a Heuristic func based on embeddings
    Use LengthBasedRef.
    """
    __slots__ = 'search_tree', 'concepts_to_ignore', 'min_length'

    name = 'LengthBaseLearner'

    kb: KnowledgeBase
    search_tree: LBLSearchTree
    min_length: int

    def __init__(self, *,
                 knowledge_base: KnowledgeBase,
                 refinement_operator: Optional[BaseRefinement] = None,
                 search_tree: Optional[LBLSearchTree] = None,
                 quality_func: Optional[AbstractScorer] = None,
                 heuristic_func: Optional[AbstractHeuristic] = None,
                 iter_bound: int = 10_000,
                 terminate_on_goal: bool = False,
                 max_num_of_concepts_tested: int = 10_000,
                 min_length: int = 1,
                 ignored_concepts=None):

        if ignored_concepts is None:
            ignored_concepts = {}
        if refinement_operator is None:
            refinement_operator = LengthBasedRefinement(knowledge_base=knowledge_base)
        if quality_func is None:
            quality_func = F1()
        if heuristic_func is None:
            heuristic_func = CELOEHeuristic()
        if search_tree is None:
            search_tree = SearchTreePriorityQueue(quality_func=quality_func, heuristic_func=heuristic_func)

        super().__init__(knowledge_base=knowledge_base,
                         refinement_operator=refinement_operator,
                         quality_func=quality_func,
                         heuristic_func=heuristic_func,
                         terminate_on_goal=terminate_on_goal,
                         iter_bound=iter_bound,
                         max_num_of_concepts_tested=max_num_of_concepts_tested
                         )
        self.search_tree = search_tree
        self.concepts_to_ignore = ignored_concepts
        self.min_length = min_length

    def get_node(self, c: OWLClassExpression, **kwargs):
        return LBLNode(c, self.kb.cl(c), self.kb.individuals_set(c), **kwargs)

    def next_node_to_expand(self, step) -> LBLNode:
        return self.search_tree.get_most_promising()

    def downward_refinement(self, node: LBLNode) -> Iterable[LBLNode]:
        assert isinstance(node, LBLNode)
        refinements = (self.get_node(i, parent_node=node) for i in
                       self.operator.refine(node.concept, max_length=node.len + 1 + self.min_length)
                       if i not in self.concepts_to_ignore)
        return refinements

    def fit(self, learning_problem: AbstractLearningProblem):
        """
        Find hypotheses that explain pos and neg.
        """
        self.clean()
        assert isinstance(learning_problem, AbstractLearningProblem)
        kb_learning_problem = learning_problem.encode_kb(knowledge_base=self.kb)
        self.start_time = time.time()
        root = self.get_node(self.start_class, is_root=True)
        self.search_tree.add_root(node=root, kb_learning_problem=kb_learning_problem)
        self._number_of_tested_concepts = 1
        for j in range(1, self.iter_bound):
            most_promising = self.next_node_to_expand(j)
            for ref in self.downward_refinement(most_promising):
                goal_found = self.search_tree.add_node(node=ref, parent_node=most_promising,
                                                       kb_learning_problem=kb_learning_problem)
                self._number_of_tested_concepts += 1
                if goal_found:
                    if self.terminate_on_goal:
                        return self.terminate()
            if self.number_of_tested_concepts >= self.max_num_of_concepts_tested:
                return self.terminate()
        return self.terminate()

    def clean(self):
        self.search_tree.clean()
        self.concepts_to_ignore.clear()
        super().clean()

    def best_hypotheses(self, n=10) -> Iterable[LBLNode]:
        yield from self.search_tree.get_top_n(n)

    def show_search_tree(self, heading_step: str, top_n: int = 10) -> None:
        rdr = DLSyntaxObjectRenderer()

        self.search_tree.show_search_tree(root_concept=self.start_class, heading_step=heading_step)

        print('######## ', heading_step, 'step Best Hypotheses ###########')

        predictions = list(self.best_hypotheses(top_n))
        for ith, node in enumerate(predictions):
            print('{0}-\t{1}\t{2}:{3}\tHeuristic:{4}:'.format(ith + 1, rdr.render(node.concept),
                                                              type(self.quality_func).name, node.quality,
                                                              node.heuristic))
        print('######## Search Tree ###########\n')


class CustomConceptLearner(CELOE):
    def __init__(self, knowledge_base, quality_func=None, iter_bound=None, max_num_of_concepts_tested=None,
                 heuristic_func=None,
                 ignored_concepts=None, verbose=None, terminate_on_goal=None):
        super().__init__(knowledge_base=knowledge_base,
                         quality_func=quality_func,
                         heuristic_func=heuristic_func,
                         ignored_concepts=ignored_concepts,
                         terminate_on_goal=terminate_on_goal,
                         iter_bound=iter_bound, max_num_of_concepts_tested=max_num_of_concepts_tested, verbose=verbose)
        self.name = heuristic_func.name
