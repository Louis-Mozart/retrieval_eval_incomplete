# -----------------------------------------------------------------------------
# MIT License
#
# Copyright (c) 2024 Ontolearn Team
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------

from itertools import chain
from typing import Optional, Callable, Tuple, Generator, List, Union, Final
import pandas
import matplotlib.pyplot as plt
import sklearn
import numpy as np
from owlapy.class_expression import OWLClass, OWLClassExpression
from owlapy.iri import IRI
from owlapy.owl_axiom import OWLEquivalentClassesAxiom
from owlapy.owl_ontology import OWLOntology
from owlapy.owl_ontology_manager import OWLOntologyManager, OntologyManager
from owlapy.owl_hierarchy import ClassHierarchy, ObjectPropertyHierarchy, DatatypePropertyHierarchy
from owlapy.utils import OWLClassExpressionLengthMetric, LRUCache
import traceback
from typing import Iterable
from tqdm import tqdm


def make_iterable_verbose(iterable_object, verbose, desc="Default", position=None, leave=True) -> Iterable:
    if verbose > 0:
        return tqdm(iterable_object, desc=desc, position=position, leave=leave)
    else:
        return iterable_object


def init_length_metric(length_metric: Optional[OWLClassExpressionLengthMetric] = None,
                       length_metric_factory: Optional[Callable[[], OWLClassExpressionLengthMetric]] = None):
    """ Initialize the technique on computing length of a concept"""
    if length_metric is not None:
        pass
    elif length_metric_factory is not None:
        length_metric = length_metric_factory()
    else:
        length_metric = OWLClassExpressionLengthMetric.get_default()

    return length_metric


def init_hierarchy_instances(reasoner, class_hierarchy, object_property_hierarchy, data_property_hierarchy) -> Tuple[
    ClassHierarchy, ObjectPropertyHierarchy, DatatypePropertyHierarchy]:
    """ Initialize class, object property, and data property hierarchies """
    if class_hierarchy is None:
        class_hierarchy = ClassHierarchy(reasoner)

    if object_property_hierarchy is None:
        object_property_hierarchy = ObjectPropertyHierarchy(reasoner)

    if data_property_hierarchy is None:
        data_property_hierarchy = DatatypePropertyHierarchy(reasoner)

    assert class_hierarchy is None or isinstance(class_hierarchy, ClassHierarchy)
    assert object_property_hierarchy is None or isinstance(object_property_hierarchy, ObjectPropertyHierarchy)
    assert data_property_hierarchy is None or isinstance(data_property_hierarchy, DatatypePropertyHierarchy)

    return class_hierarchy, object_property_hierarchy, data_property_hierarchy


def init_named_individuals(individuals_cache_size, ):
    use_individuals_cache = individuals_cache_size > 0
    if use_individuals_cache:
        _ind_cache = LRUCache(maxsize=individuals_cache_size)
    else:
        _ind_cache = None
    return use_individuals_cache, _ind_cache


def init_individuals_from_concepts(include_implicit_individuals: bool = None, reasoner=None, ontology=None,
                                   individuals_per_concept=None):
    assert isinstance(include_implicit_individuals, bool), f"{include_implicit_individuals} must be boolean"
    if include_implicit_individuals:
        assert isinstance(individuals_per_concept, Generator)
        # get all individuals from concepts
        _ind_set = frozenset(chain.from_iterable(individuals_per_concept))
    else:
        # @TODO: needs to be explained
        individuals = ontology.individuals_in_signature()
        _ind_set = frozenset(individuals)
    return _ind_set


def compute_tp_fn_fp_tn(individuals, pos, neg):
    tp = len(pos.intersection(individuals))
    tn = len(neg.difference(individuals))
    fp = len(neg.intersection(individuals))
    fn = len(pos.difference(individuals))
    return tp, fn, fp, tn


def compute_f1_score(individuals, pos, neg) -> float:
    """ Compute F1-score of a concept
    """
    assert type(individuals) == type(pos) == type(neg), f"Types must match:{type(individuals)},{type(pos)},{type(neg)}"
    # true positive: |E^+ AND R(C)  |
    tp = len(pos.intersection(individuals))
    # true negative : |E^- AND R(C)|
    tn = len(neg.difference(individuals))

    # false positive : |E^- AND R(C)|
    fp = len(neg.intersection(individuals))
    # false negative : |E^- \ R(C)|
    fn = len(pos.difference(individuals))

    try:
        recall = tp / (tp + fn)
    except ZeroDivisionError:
        return 0.0

    try:
        precision = tp / (tp + fp)
    except ZeroDivisionError:
        return 0.0

    if precision == 0 or recall == 0:
        return 0.0

    f_1 = 2 * ((precision * recall) / (precision + recall))
    return f_1


def plot_umap_reduced_embeddings(X: pandas.DataFrame, y: List[float], name: str = "umap_visualization.pdf") -> None:
    import umap
    reducer = umap.UMAP(random_state=1)
    embedding = reducer.fit_transform(X)
    plt.scatter(embedding[:, 0], embedding[:, 1],
                c=["r" if x == 1 else "b" for x in y])
    plt.grid()
    plt.gca().set_aspect('equal', 'datalim')
    plt.savefig(name)
    plt.show()


def plot_decision_tree_of_expressions(feature_names, cart_tree) -> None:
    """
    Plot the built CART Decision Tree and feature importance.

    Parameters:
        feature_names (list): A list of feature names used in the decision tree.
        cart_tree: The trained CART Decision Tree model.

    Returns:
        None

    Notes:
        This function plots the decision tree using matplotlib and saves it to a PDF file named 'cart_decision_tree.pdf'.
        It also displays the plot.
    """
    plt.figure(figsize=(10, 10))
    sklearn.tree.plot_tree(cart_tree, fontsize=10, feature_names=feature_names, class_names=["Negative", "Positive"],
                           filled=True)
    plt.savefig('cart_decision_tree.pdf')
    plt.show()

def plot_topk_feature_importance(feature_names, cart_tree, topk: int = 10)->None:
    """
    Plot the feature importance of the CART Decision Tree.

    Parameters:
        feature_names (list): A list of feature names used in the decision tree.
        cart_tree: The trained CART Decision Tree model.
        topk (int, optional): The number of top features to display. Defaults to 10.

    Returns:
        None

    Notes:
        This function plots a bar chart showing the importance of each feature in the decision tree,
        with the top k features displayed. The importance is measured by the normalized total reduction.
        The plot is displayed using matplotlib.
    """
    fig, ax = plt.subplots()
    topk_id = np.argsort(cart_tree.feature_importances_)[-topk:]
    expressions = [feature_names[i] for i in topk_id.tolist()]
    feature_importance = cart_tree.feature_importances_[topk_id]
    ax.bar(x=expressions, height=feature_importance)
    ax.set_ylabel('Normalized total reduction')
    ax.set_title('Feature Importance')
    plt.xticks(rotation=90, ha='right')
    fig.tight_layout()
    plt.show()


def save_owl_class_expressions(expressions: Union[OWLClassExpression, List[OWLClassExpression]],
                               path: str = 'Predictions',
                               rdf_format: str = 'rdfxml') -> None:
    assert isinstance(expressions, OWLClassExpression) or isinstance(expressions[0],
                                                                     OWLClassExpression), "expressions must be either OWLClassExpression or a list of OWLClassExpression"
    if isinstance(expressions, OWLClassExpression):
        expressions = [expressions]
    NS: Final = 'https://dice-research.org/predictions#'

    if rdf_format != 'rdfxml':
        raise NotImplementedError(f'Format {rdf_format} not implemented.')
    # @TODO: CD: Lazy import. CD: Can we use rdflib to serialize concepts ?!
    from owlapy.owl_ontology import Ontology
    # ()
    manager: OWLOntologyManager = OntologyManager()
    # ()
    ontology: OWLOntology = manager.create_ontology(IRI.create(NS))
    # () Iterate over concepts
    for th, i in enumerate(expressions):
        cls_a = OWLClass(IRI.create(NS, str(th)))
        equivalent_classes_axiom = OWLEquivalentClassesAxiom([cls_a, i])
        try:
            manager.add_axiom(ontology, equivalent_classes_axiom)
        except AttributeError:
            print(traceback.format_exc())
            print("Exception at creating OWLEquivalentClassesAxiom")
            print(equivalent_classes_axiom)
            print(cls_a)
            print(i)
            print(expressions)
            exit(1)
    manager.save_ontology(ontology, IRI.create('file:/' + path + '.owl'))
