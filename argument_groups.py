# Knowledge graph related arguments
knowledge_graph_args = [
    ("--knowledge_base_path", str, "KGs/Family/family-benchmark_rich_background.owl",
        "Path to the knowledge base/ontology. This file contains '.owl' extension, e.g. 'some/path/kb.owl'"),
    ("--sparql_endpoint", str, None,
        "An endpoint of a triple store, e.g. 'http://localhost:3030/family/sparql'."),
    ("--path_of_embeddings", str, 'NCESData/family/embeddings/ConEx_entity_embeddings.csv',
        "Path to knowledge base embeddings. Some models like NCES require this, e.g. 'some/path/kb_embeddings.csv'"),
    ("--save", bool, False, "Save the hypothesis?"),
    ("--path_learning_problem", str, 'examples/uncle_lp2.json',
        "Path to a .json file that contains 2 properties 'positive_examples' and 'negative_examples'."),
    ("--quality_metric", str, 'f1',
        "Quality metric.", ["f1", "accuracy", "recall", "precision", "weighted_accuracy"]),
    ("--max_runtime", int, 5, "Maximum runtime.")
]

# Model-specific arguments
model_specific_args = [
    ("--terminate_on_goal", bool, True, "Terminate when finding concept of quality 1.0?"),
    ("--use_card_restrictions", bool, True, "Use cardinality restrictions for object properties?"),
    ("--use_inverse", bool, True, "Use inverse."),
    ("--card_limit", int, 10, "Cardinality limit for object properties."),
    ("--max_nr_splits", int, 12, "Maximum number of splits."),
    ("--max_results", int, 10, "Maximum results to find (not to show)"),
    ("--iter_bound", int, 10_000, "Iterations bound."),
    ("--max_num_of_concepts_tested", int, 10_000, "Maximum number of concepts tested."),
    ("--best_only", bool, True, "Best results only?"),
    ("--calculate_min_max", bool, True, "Only for statistical purpose."),
    ("--gain_bonus_factor", float, 0.3, "Factor that weighs the increase in quality compared to the parent node."),
    ("--expansion_penalty_factor", float, 0.1, 
        "The value that is subtracted from the heuristic for each horizontal expansion of this."),
    ("--max_child_length", int, 10, "Maximum child length"),
    ("--use_negation", bool, True, "Use negation?"),
    ("--use_all_constructor", bool, True, "Use all constructors?"),
    ("--use_numeric_datatypes", bool, True, "Use numeric data types?"),
    ("--use_time_datatypes", bool, True, "Use time datatypes?"),
    ("--use_boolean_datatype", bool, True, "Use boolean datatypes?"),
    ("--start_node_bonus", float, 0.1, "Special value added to the root node."),
    ("--node_refinement_penalty", float, 0.001, "Node refinement penalty."),
]

# EvoLearner specific arguments
evo_learner_args = [
    ("--use_data_properties", bool, True, "Use data properties?"),
    ("--tournament_size", int, 7, "Tournament size."),
    ("--population_size", int, 800, "Population size."),
    ("--num_generations", int, 200, "Number of generations."),
    ("--height_limit", int, 17, "Height limit."),
    ("--gain", int, 2048, "Gain."),
    ("--penalty", int, 1, "Penalty."),
    ("--max_t", int, 2, "Number of paths."),
    ("--jump_pr", float, 0.5, "Probability to explore paths of length 2."),
    ("--crossover_pr", float, 0.9, "Crossover probability."),
    ("--mutation_pr", float, 0.1, "Mutation probability"),
    ("--elitism", bool, False, "Elitism."),
    ("--elite_size", float, 0.1, "Elite size"),
    ("--min_height", int, 1, "Minimum height of trees"),
    ("--max_height", int, 3, "Maximum height of trees"),
    ("--init_method_type", str, "RAMPED_HALF_HALF",
    "Random initialization method.", ["GROW", "FULL", "RAMPED_HALF_HALF"])
]

# NCES specific arguments
nces_args = [
    ("--learner_names", str, ["SetTransformer"], "Learner name.", ["SetTransformer", "GRU", "LSTM"]),
    ("--proj_dim", int, 128, "Number of projection dimensions."),
    ("--rnn_n_layers", int, 2, "Number of RNN layers (only for LSTM and GRU)."),
    ("--drop_prob", float, 0.1, "Drop probability."),
    ("--num_heads", int, 4, "Number of heads"),
    ("--num_seeds", int, 1, "Number of seeds (only for SetTransformer)."),
    ("--m", int, 32, "Number of inducing points (only for SetTransformer)."),
    ("--ln", bool, False, "Layer normalization (only for SetTransformer)."),
    ("--learning_rate", float, 1e-4, "Learning rate."),
    ("--decay_rate", int, 0, "Decay rate."),
    ("--clip_value", int, 5, "Clip value."),
    ("--batch_size", int, 256, "Batch size"),
    ("--num_workers", int, 8, "Number of workers"),
    ("--max_length", int, 48, "Maximum length"),
    ("--load_pretrained", bool, True, "Load pretrained."),
    ("--sorted_examples", bool, True, "Sorted examples.")
]
