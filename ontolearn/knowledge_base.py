import logging
import random
from functools import singledispatchmethod
from typing import Iterable, Optional, Callable, overload, Union, FrozenSet

from owlapy.model import OWLOntologyManager, OWLOntology, OWLReasoner, OWLClassExpression, OWLNamedIndividual, \
    OWLObjectProperty, OWLClass, OWLDataProperty, IRI
from owlapy.render import DLSyntaxObjectRenderer
from owlapy.util import iter_count, LRUCache
from .abstracts import AbstractKnowledgeBase, AbstractScorer, EncodedLearningProblem, AbstractLearningProblem
from .concept_generator import ConceptGenerator
from .core.owl.utils import OWLClassExpressionLengthMetric
from .learning_problem import PosNegLPStandard, EncodedPosNegLPStandard

Factory = Callable

logger = logging.getLogger(__name__)

# TODO:CD: To many non pythonic functions
def _Default_OntologyManagerFactory(world_store=None) -> OWLOntologyManager:
    from owlapy.owlready2 import OWLOntologyManager_Owlready2

    return OWLOntologyManager_Owlready2(world_store=world_store)

def _Default_ReasonerFactory(onto: OWLOntology) -> OWLReasoner:
    from owlapy.owlready2 import OWLOntology_Owlready2
    from owlapy.owlready2.temp_classes import OWLReasoner_Owlready2_TempClasses
    from owlapy.fast_instance_checker import OWLReasoner_FastInstanceChecker

    assert isinstance(onto, OWLOntology_Owlready2)
    base_reasoner = OWLReasoner_Owlready2_TempClasses(ontology=onto)
    reasoner = OWLReasoner_FastInstanceChecker(ontology=onto,
                                               base_reasoner=base_reasoner)
    return reasoner

def _Default_ClassExpressionLengthMetricFactory() -> OWLClassExpressionLengthMetric:
    return OWLClassExpressionLengthMetric.get_default()

class EvaluatedConcept:
    """This class is used to explicitly declare the attributes that should be returned by the evaluate_concept method.
    This way, Python uses a more efficient way to store the instance attributes, which can significantly reduce the
    memory usage
    """
    __slots__ = 'q', 'inds', 'ic'
    pass

# TODO:CD: __init__ is overcrowded. This bit can/should be simplified to few lines
# TODO:CD: Namings are not self-explanatory: User does not need to know
#  a) factory programming pattern b) Manager Classes etc inadvertently increases cognitive load
class KnowledgeBase(AbstractKnowledgeBase, ConceptGenerator):
    """Knowledge Base Class is used to represent an OWL knowledge base in Ontolearn, meaning that it represents the
    Tbox and Abox along with concept hierarchies

    Args:
        path: path to an ontology file that is to be loaded
        ontologymanager_factory: factory that creates an ontology manager to be used to load the file
        ontology: OWL ontology object
        reasoner_factory: factory that creates a reasoner to reason about the ontology
        reasoner: reasoner over the ontology
        length_metric_factory: see `length_metric`
        length_metric: length metric that is used in calculation of class expresion lengths
        individuals_cache_size: how many individuals of class expressions to cache
    """
    __slots__ = '_manager', '_ontology', '_reasoner', '_length_metric', \
                '_ind_set', '_ind_cache', 'path', 'use_individuals_cache'

    _manager: OWLOntologyManager
    _ontology: OWLOntology
    _reasoner: OWLReasoner

    _length_metric: OWLClassExpressionLengthMetric

    _ind_set: FrozenSet[OWLNamedIndividual]
    _ind_cache: LRUCache[OWLClassExpression, FrozenSet[OWLNamedIndividual]]  # class expression => individuals

    path: str
    use_individuals_cache: bool

    # The simplest way to create an instance of this class is by just passing the 'path' of the OWL knowledge base in
    # the constructor
    @overload
    def __init__(self, *,
                 path: str,
                 ontologymanager_factory: Factory[[], OWLOntologyManager] = _Default_OntologyManagerFactory,
                 reasoner_factory: Factory[[OWLOntology], OWLReasoner] = _Default_ReasonerFactory,
                 length_metric: Optional[OWLClassExpressionLengthMetric] = None,
                 length_metric_factory: Optional[Factory[[], OWLClassExpressionLengthMetric]] = None,
                 individuals_cache_size=128,
                 backend_store: bool = False):
        ...

    @overload
    def __init__(self, *,
                 ontology: OWLOntology,
                 reasoner: OWLReasoner,
                 length_metric: Optional[OWLClassExpressionLengthMetric] = None,
                 length_metric_factory: Optional[Factory[[], OWLClassExpressionLengthMetric]] = None,
                 individuals_cache_size=128):
        ...

    def __init__(self, *,
                 path: Optional[str] = None,

                 ontologymanager_factory: Optional[Factory[[], OWLOntologyManager]] = None,
                 reasoner_factory: Optional[Factory[[OWLOntology], OWLReasoner]] = None,
                 length_metric_factory: Optional[Factory[[], OWLClassExpressionLengthMetric]] = None,

                 ontology: Optional[OWLOntology] = None,
                 reasoner: Optional[OWLReasoner] = None,
                 length_metric: Optional[OWLClassExpressionLengthMetric] = None,

                 individuals_cache_size=128,
                 backend_store: bool = False):
        AbstractKnowledgeBase.__init__(self)
        self.path = path

        """
            In the code below, until the first method of the class, 
            we assign some of the class attributes depending on
            the arguments passed on the instance initialization. 
        """
        if ontology is not None:
            self._manager = ontology.get_owl_ontology_manager()
            self._ontology = ontology
        elif ontologymanager_factory is not None:
            self._manager = ontologymanager_factory()
        else:  # default to Owlready2 implementation
            if path is not None and backend_store:
                self._manager = _Default_OntologyManagerFactory(world_store=path + ".or2")
            else:
                self._manager = _Default_OntologyManagerFactory()
            # raise TypeError("neither ontology nor manager factory given")

        if ontology is None:
            if path is None:
                raise TypeError("path missing")
            self._ontology = self._manager.load_ontology(IRI.create('file://' + self.path))

            from owlapy.owlready2 import OWLOntologyManager_Owlready2
            if isinstance(self._manager, OWLOntologyManager_Owlready2) and backend_store:
                self._manager.save_world()
                logger.debug("Synced world to backend store")

        if reasoner is not None:
            self._reasoner = reasoner
        elif reasoner_factory is not None:
            self._reasoner = reasoner_factory(self._ontology)
        else:  # default to fast instance checker
            self._reasoner = _Default_ReasonerFactory(self._ontology)
            # raise TypeError("neither reasoner nor reasoner factory given")

        if length_metric is not None:
            self._length_metric = length_metric
        elif length_metric_factory is not None:
            self._length_metric = length_metric_factory()
        else:
            self._length_metric = _Default_ClassExpressionLengthMetricFactory()

        ConceptGenerator.__init__(self, reasoner=self._reasoner)

        from owlapy.fast_instance_checker import OWLReasoner_FastInstanceChecker
        if isinstance(self._reasoner, OWLReasoner_FastInstanceChecker):
            self._ind_set = self._reasoner._ind_set  # performance hack
        else:
            individuals = self._ontology.individuals_in_signature()
            self._ind_set = frozenset(individuals)

        self.use_individuals_cache = individuals_cache_size > 0
        if self.use_individuals_cache:
            self._ind_cache = LRUCache(maxsize=individuals_cache_size)

        self.describe()

    """____________________________↓ Class Methods ↓____________________________"""

    def ontology(self) -> OWLOntology:
        """Get the root Ontology loaded in this knowledge base

        Returns:
            The Ontology
        """

        return self._ontology

    def reasoner(self) -> OWLReasoner:
        """Get the Reasoner loaded in this knowledge base

        Returns:
            The Reasoner
        """

        return self._reasoner

    def ignore_and_copy(self, ignored_classes: Optional[Iterable[OWLClass]] = None,
                        ignored_object_properties: Optional[Iterable[OWLObjectProperty]] = None,
                        ignored_data_properties: Optional[Iterable[OWLDataProperty]] = None) -> 'KnowledgeBase':
        """Makes a copy of the knowledge base while ignoring specified concepts and properties

        Args:
            ignored_classes: classes to ignore
            ignored_object_properties: object properties to ignore
            ignored_data_properties: data properties to ignore
        Returns:
            A new KnowledgeBase with the hierarchies restricted as requested
        """

        new = object.__new__(KnowledgeBase)

        AbstractKnowledgeBase.__init__(new)
        new._manager = self._manager
        new._ontology = self._ontology
        new._reasoner = self._reasoner
        new._length_metric = self._length_metric
        new._ind_set = self._ind_set
        new.path = self.path
        new.use_individuals_cache = self.use_individuals_cache

        if self.use_individuals_cache:
            new._ind_cache = LRUCache(maxsize=self._ind_cache.maxsize)

        if ignored_classes is not None:
            owl_concepts_to_ignore = set()
            for i in ignored_classes:
                if self.contains_class(i):
                    owl_concepts_to_ignore.add(i)
                else:
                    raise ValueError(
                        f'{i} could not found in \n{self} \n'
                        f'{[_ for _ in self.ontology().classes_in_signature()]}.')
            if logger.isEnabledFor(logging.INFO):
                r = DLSyntaxObjectRenderer()
                logger.info('Concepts to ignore: {0}'.format(' '.join(map(r.render, owl_concepts_to_ignore))))
            class_hierarchy = self._class_hierarchy.restrict_and_copy(remove=owl_concepts_to_ignore)
        else:
            class_hierarchy = self._class_hierarchy

        if ignored_object_properties is not None:
            object_property_hierarchy = self._object_property_hierarchy.restrict_and_copy(
                remove=ignored_object_properties)
        else:
            object_property_hierarchy = self._object_property_hierarchy

        if ignored_data_properties is not None:
            data_property_hierarchy = self._data_property_hierarchy.restrict_and_copy(remove=ignored_data_properties)
        else:
            data_property_hierarchy = self._data_property_hierarchy

        ConceptGenerator.__init__(new,
                                  reasoner=self._reasoner,
                                  class_hierarchy=class_hierarchy,
                                  object_property_hierarchy=object_property_hierarchy,
                                  data_property_hierarchy=data_property_hierarchy)

        return new

    def concept_len(self, ce: OWLClassExpression) -> int:
        """Calculates the length of a concept and is used by some concept learning algorithms to
        find the best results considering also the length of the concepts

        Args:
            ce: the concept to be measured
        Returns:
            Length of the concept
        """

        return self._length_metric.length(ce)

    def clean(self):
        """Clean all stored values (states and caches) if there is any

        Note:
            1. If you have more than one learning problem that you want to fit to the same model (i.e. to learn the
            concept using the same concept learner model) use this method to make sure that you have cleared every
            previous stored value.
            2. If you store another KnowledgeBase instance using the same variable name as before, it is recommended to
            use this method before the initialization to avoid data mismatch.
        """

        ConceptGenerator.clean(self)
        if self.use_individuals_cache:
            self._ind_cache.cache_clear()

    def _cache_individuals(self, ce: OWLClassExpression) -> None:
        if not self.use_individuals_cache:
            raise TypeError
        if ce in self._ind_cache:
            return
        from owlapy.fast_instance_checker import OWLReasoner_FastInstanceChecker
        if isinstance(self._reasoner, OWLReasoner_FastInstanceChecker):
            self._ind_cache[ce] = self._reasoner._find_instances(ce)  # performance hack
        else:
            temp = self._reasoner.instances(ce)
            self._ind_cache[ce] = frozenset(temp)

    def _maybe_cache_individuals(self, ce: OWLClassExpression) -> Iterable[OWLNamedIndividual]:
        if self.use_individuals_cache:
            self._cache_individuals(ce)
            yield from self._ind_cache[ce]
        else:
            yield from self._reasoner.instances(ce)

    def _maybe_cache_individuals_count(self, ce: OWLClassExpression) -> int:
        if self.use_individuals_cache:
            self._cache_individuals(ce)
            r = self._ind_cache[ce]
            return len(r)
        else:
            return iter_count(self._reasoner.instances(ce))

    def individuals(self, concept: Optional[OWLClassExpression] = None) -> Iterable[OWLNamedIndividual]:
        """Retrieve all individuals belonging to the concept in the ontology. If the concept property is not
        specified then it returns all the individuals

        Args:
            concept: class expression of which to list individuals
        Returns:
            Individuals belonging to the given class
        """

        if concept is None or concept.is_owl_thing():
            for i in self._ind_set:
                yield i
        else:
            yield from self._maybe_cache_individuals(concept)

    def individuals_count(self, concept: Optional[OWLClassExpression] = None) -> int:
        """Returns the number of all individuals belonging to the concept in the ontology

        Args:
            concept: class expression of the individuals to count
        Returns:
            Number of the individuals belonging to the given class
        """

        if concept is None or concept.is_owl_thing():
            return len(self._ind_set)
        else:
            return self._maybe_cache_individuals_count(concept)

    @overload
    def individuals_set(self, concept: OWLClassExpression):
        ...

    @overload
    def individuals_set(self, individual: OWLNamedIndividual):
        ...

    @overload
    def individuals_set(self, individuals: Iterable[OWLNamedIndividual]):
        ...

    def individuals_set(self, arg: Union[Iterable[OWLNamedIndividual], OWLNamedIndividual, OWLClassExpression]):
        """Retrieve the individuals specified in the arg as a frozenset. If `arg` is an OWLClassExpression then this
        method behaves as the method "individuals" but will return the final result as a frozenset

        Args:
            arg: more than one individual
                single individual
                class expression of which to list individuals
        Returns:
            frozenset of the individuals depending on the arg type
        """

        if isinstance(arg, OWLClassExpression):
            if self.use_individuals_cache:
                self._cache_individuals(arg)
                r = self._ind_cache[arg]
                return r
            else:
                return frozenset(self.individuals(arg))
        elif isinstance(arg, OWLNamedIndividual):
            return frozenset({arg})
        else:
            return frozenset(arg)

    def all_individuals_set(self):
        """Retrieve all the individuals of the knowledge base

        Returns:
            frozenset of the all individuals
        """

        if self._ind_set is not None:
            return self._ind_set
        else:
            return frozenset(self._ontology.individuals_in_signature())

    def most_general_object_properties(self, *, domain: OWLClassExpression, inverse: bool = False) \
            -> Iterable[OWLObjectProperty]:
        assert isinstance(domain, OWLClassExpression)

        func = self.get_object_property_ranges if inverse else self.get_object_property_domains

        inds_domain = self.individuals_set(domain)
        for prop in self._object_property_hierarchy.most_general_roles():
            if domain.is_owl_thing() or inds_domain <= self.individuals_set(func(prop)):
                yield prop

    def _data_properties_for_domain(self, domain: OWLClassExpression, data_properties: Iterable[OWLDataProperty]) \
            -> Iterable[OWLDataProperty]:
        assert isinstance(domain, OWLClassExpression)

        inds_domain = self.individuals_set(domain)
        for prop in data_properties:
            if domain.is_owl_thing() or inds_domain <= self.individuals_set(self.get_data_property_domains(prop)):
                yield prop

    def __repr__(self):
        properties_count = iter_count(self.ontology().object_properties_in_signature()) + iter_count(
            self.ontology().data_properties_in_signature())
        class_count = iter_count(self.ontology().classes_in_signature())
        individuals_count = self.individuals_count()

        return f'KnowledgeBase(path={repr(self.path)} <{class_count} classes, {properties_count} properties, ' \
               f'{individuals_count} individuals)'

    @singledispatchmethod
    def encode_learning_problem(self, lp: AbstractLearningProblem):
        raise NotImplementedError(lp)

    @encode_learning_problem.register
    def _(self, lp: PosNegLPStandard):
        """Provides the encoded learning problem (lp), i.e. the class containing the set of OWLNamedIndividuals
        as follows:
            kb_pos --> the positive examples set
            kb_neg --> the negative examples set
            kb_all --> all lp individuals / all individuals set
            kb_diff --> kb_all - (kb_pos + kb_neg)
        Note:
            Simple access of the learning problem individuals divided in respective sets.
            You will need the encoded learning problem to use the method evaluate_concept of this class.
        Args:
            lp: the learning problem
        Return:
            The encoded learning problem
        """

        assert len(self.class_hierarchy()) > 0

        if lp.all is None:
            kb_all = self.all_individuals_set()
        else:
            kb_all = self.individuals_set(lp.all)

        assert 0 < len(lp.pos) < len(kb_all) and len(kb_all) > len(lp.neg)
        if logger.isEnabledFor(logging.INFO):
            r = DLSyntaxObjectRenderer()
            logger.info('E^+:[ {0} ]'.format(', '.join(map(r.render, lp.pos))))
            logger.info('E^-:[ {0} ]'.format(', '.join(map(r.render, lp.neg))))

        kb_pos = self.individuals_set(lp.pos)
        if len(lp.neg) == 0:  # if negatives are not provided, randomly sample.
            kb_neg = type(kb_all)(random.sample(list(kb_all), len(kb_pos)))
        else:
            kb_neg = self.individuals_set(lp.neg)

        try:
            assert len(kb_pos) == len(lp.pos)
        except AssertionError:
            print(lp.pos)
            print(kb_pos)
            print(kb_all)
            print('Assertion error. Exiting.')
            raise
        if lp.neg:
            assert len(kb_neg) == len(lp.neg)

        return EncodedPosNegLPStandard(
            kb_pos=kb_pos,
            kb_neg=kb_neg,
            kb_all=kb_all,
            kb_diff=kb_all.difference(kb_pos.union(kb_neg)))

    def evaluate_concept(self, concept: OWLClassExpression, quality_func: AbstractScorer,
                         encoded_learning_problem: EncodedLearningProblem) -> EvaluatedConcept:
        """Evaluates a concept by using the encoded learning problem examples, in terms of Accuracy or F1-score

        Note:
            This method is useful to tell the quality (e.q) of a generated concept by the concept learners, to get
            the set of individuals (e.inds) that are classified by this concept and the amount of them (e.ic).
        Args:
            concept: the concept to be evaluated
            quality_func: quality measurement in terms of Accuracy or F1-score
            encoded_learning_problem: the encoded learning problem
        Return:
            The evaluated concept
        """

        e = EvaluatedConcept()
        e.inds = self.individuals_set(concept)
        e.ic = len(e.inds)
        _, e.q = quality_func.score_elp(e.inds, encoded_learning_problem)
        return e

    async def evaluate_concept_async(self, concept: OWLClassExpression, quality_func: AbstractScorer,
                                     encoded_learning_problem: EncodedLearningProblem) -> EvaluatedConcept:
        """The asynchronous version of evaluate_concept

        Raises:
            NotImplementedError: This method is not implemented yet
        """
        raise NotImplementedError
