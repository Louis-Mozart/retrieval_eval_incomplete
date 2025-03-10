import unittest
from typing import TypeVar

from owlapy.class_expression import OWLClass
from owlapy.iri import IRI
from owlapy.owl_property import OWLObjectProperty

from owlapy.owl_hierarchy import ClassHierarchy, ObjectPropertyHierarchy, AbstractHierarchy
from ontolearn.utils import setup_logging
from owlapy.owl_reasoner import StructuralReasoner
from owlapy.owl_ontology_manager import OntologyManager

_T = TypeVar('_T')  #:

setup_logging("ontolearn/logging_test.conf")


class Owl_Core_PropertyHierarchy_Test(unittest.TestCase):
    def test_object_property_hierarchy(self):
        NS = "http://www.biopax.org/examples/glycolysis#"
        mgr = OntologyManager()
        onto = mgr.load_ontology(IRI.create("file://KGs/Biopax/biopax.owl"))
        reasoner = StructuralReasoner(onto)

        oph = ObjectPropertyHierarchy(reasoner)
        # for k in sorted(oph.roots()):
        #     _print_children(oph, k)

        participants = OWLObjectProperty(IRI.create(NS, 'PARTICIPANTS'))
        target_props = frozenset({OWLObjectProperty(IRI(NS, 'COFACTOR')),
                                  OWLObjectProperty(IRI(NS, 'CONTROLLED')),
                                  OWLObjectProperty(IRI(NS, 'CONTROLLER')),
                                  OWLObjectProperty(IRI(NS, 'LEFT')),
                                  OWLObjectProperty(IRI(NS, 'RIGHT'))})
        self.assertEqual(frozenset(oph.sub_object_properties(participants)), target_props)


class Owl_Core_ClassHierarchy_Test(unittest.TestCase):
    # TODO
    # def test_class_hierarchy_circle(self):
    #     NS = "http://example.org/circle#"
    #     a1 = OWLClass(IRI.create(NS, 'A1'))
    #     a3 = OWLClass(IRI.create(NS, 'A3'))
    #     a2 = OWLClass(IRI.create(NS, 'A2'))
    #     a0 = OWLClass(IRI.create(NS, 'A0'))
    #     a4 = OWLClass(IRI.create(NS, 'A4'))
    #     ch = ClassHierarchy({a1: [a2],
    #                          a2: [a3],
    #                          a3: [a1, a4],
    #                          a0: [a1],
    #                          a4: []}.items())
    #     for k in sorted(ch.roots()):
    #         _print_children(ch, k)

    def test_class_hierarchy_restrict(self):
        NS = "http://www.benchmark.org/family#"
        mgr = OntologyManager()
        onto = mgr.load_ontology(IRI.create("file://KGs/Family/family-benchmark_rich_background.owl"))
        reasoner = StructuralReasoner(onto)

        ch = ClassHierarchy(reasoner).restrict_and_copy(remove=frozenset({OWLClass(IRI(NS, 'Grandchild'))}))

        target_cls = frozenset({OWLClass(IRI(NS, 'Daughter')),
                                OWLClass(IRI(NS, 'Granddaughter')),
                                OWLClass(IRI(NS, 'Grandson')),
                                OWLClass(IRI(NS, 'Son'))})
        assert frozenset(ch.sub_classes(OWLClass(IRI(NS, 'Child'))))==target_cls

    def test_class_hierarchy_children(self):
        NS = "http://example.com/father#"
        mgr = OntologyManager()
        onto = mgr.load_ontology(IRI.create("file://KGs/Family/father.owl"))
        reasoner = StructuralReasoner(onto)

        ch = ClassHierarchy(reasoner)
        # for k in sorted(ch.roots()):
        #     _print_children(ch, k)

        target_cls = frozenset({OWLClass(IRI(NS, 'female')),
                                OWLClass(IRI(NS, 'male'))})
        self.assertEqual(frozenset(ch.sub_classes(OWLClass(IRI(NS, 'person')))), target_cls)

    def test_class_hierarchy_parents_roots(self):
        NS = "http://www.benchmark.org/family#"
        mgr = OntologyManager()
        onto = mgr.load_ontology(IRI.create("file://KGs/Family/family-benchmark_rich_background.owl"))
        reasoner = StructuralReasoner(onto)

        ch = ClassHierarchy(reasoner)
        grandmother = OWLClass(IRI(NS, 'Grandmother'))
        # _print_parents(ch, grandmother)

        target_cls = frozenset({OWLClass(IRI(NS, 'Female')),
                                OWLClass(IRI(NS, 'Grandparent'))})
        assert frozenset(ch.super_classes(grandmother))== target_cls

        target_cls = frozenset({OWLClass(IRI(NS, 'Person'))})
        assert frozenset(ch.roots())== target_cls

    def test_class_hierarchy_siblings(self):
        NS = "http://www.benchmark.org/family#"
        mgr = OntologyManager()
        onto = mgr.load_ontology(IRI.create("file://KGs/Family/family-benchmark_rich_background.owl"))
        reasoner = StructuralReasoner(onto)

        ch = ClassHierarchy(reasoner)
        child = OWLClass(IRI(NS, 'Child'))
        target_cls = frozenset({OWLClass(IRI(NS, 'Parent')),
                                OWLClass(IRI(NS, 'PersonWithASibling')),
                                OWLClass(IRI(NS, 'Female')),
                                OWLClass(IRI(NS, 'Male'))})
        self.assertEqual(frozenset(ch.siblings(child)), target_cls)

    def test_class_hierarchy_leaves(self):
        NS = "http://www.benchmark.org/family#"
        mgr = OntologyManager()
        onto = mgr.load_ontology(IRI.create("file://KGs/Family/family-benchmark_rich_background.owl"))
        reasoner = StructuralReasoner(onto)

        ch = ClassHierarchy(reasoner)
        # for k in sorted(ch.roots()):
        #     _print_children(ch, k)
        children = OWLClass(IRI(NS, 'Child'))
        target_leaves = frozenset({OWLClass(IRI(NS, 'Daughter')),
                                   OWLClass(IRI(NS, 'Granddaughter')),
                                   OWLClass(IRI(NS, 'Grandson')),
                                   OWLClass(IRI(NS, 'Son'))})
        leaves = frozenset(ch.leaves(children))
        self.assertEqual(leaves, target_leaves)


# debug functions

def _print_children(hier: AbstractHierarchy[_T], c: _T, level: int = 0) -> None:
    print(' ' * 2 * level, c, '=>')
    for d in sorted(hier.children(c)):
        _print_children(hier, d, level + 1)


def _print_parents(hier: AbstractHierarchy[_T], c: _T, level: int = 0) -> None:
    print(' ' * 2 * level, c, '<=')
    for d in sorted(hier.parents(c)):
        _print_parents(hier, d, level + 1)


if __name__ == '__main__':
    unittest.main()
