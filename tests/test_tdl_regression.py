from ontolearn.learners import Drill, TDL
from ontolearn.knowledge_base import KnowledgeBase
from ontolearn.triple_store import TripleStore
from ontolearn.learning_problem import PosNegLPStandard
from ontolearn.verbalizer import LLMVerbalizer
from owlapy.model import OWLNamedIndividual, IRI, OWLObjectSomeValuesFrom, OWLObjectOneOf, OWLObjectProperty, \
    OWLClass
from owlapy.render import DLSyntaxObjectRenderer
from owlapy.owl2sparql.converter import owl_expression_to_sparql
from ontolearn.utils.static_funcs import compute_f1_score, save_owl_class_expressions
import json
import rdflib


class TestConceptLearnerReg:

    def test_regression_family(self):
        path = "KGs/Family/family-benchmark_rich_background.owl"
        kb = KnowledgeBase(path=path)
        with open("LPs/Family/lps.json") as json_file:
            settings = json.load(json_file)
        model = TDL(knowledge_base=kb, kwargs_classifier={"random_state": 1})
        for str_target_concept, examples in settings['problems'].items():
            p = set(examples['positive_examples'])
            n = set(examples['negative_examples'])
            typed_pos = set(map(OWLNamedIndividual, map(IRI.create, p)))
            typed_neg = set(map(OWLNamedIndividual, map(IRI.create, n)))
            lp = PosNegLPStandard(pos=typed_pos, neg=typed_neg)
            h = model.fit(learning_problem=lp).best_hypotheses()
            q = compute_f1_score(individuals=frozenset({i for i in kb.individuals(h)}), pos=lp.pos, neg=lp.neg)
            if str_target_concept == "Grandgrandmother":
                assert q >= 0.866
            elif str_target_concept == "Cousin":
                assert q >= 0.992
            else:
                assert q == 1.00
            # If not a valid SPARQL query, it should throw an error
            rdflib.Graph().query(owl_expression_to_sparql(root_variable="?x", ce=h))
            # Save the prediction
            save_owl_class_expressions(h, path="Predictions")
            # (Load the prediction) and check the number of owl class definitions
            g = rdflib.Graph().parse("Predictions.owl")
            # rdflib.Graph() parses named OWL Classes by the order of their definition
            named_owl_classes = [s for s, p, o in
                                 g.triples((None, rdflib.namespace.RDF.type, rdflib.namespace.OWL.Class)) if
                                 isinstance(s, rdflib.term.URIRef)]
            assert len(named_owl_classes) >= 1
            named_owl_classes.pop(0).n3() == ">https://dice-research.org/predictions#0>"