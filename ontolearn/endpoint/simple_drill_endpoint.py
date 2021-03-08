import io
from argparse import ArgumentParser
from typing import List

from flask import Flask, request, Response, abort

from ontolearn import KnowledgeBase, DrillAverage, Node
from ontolearn.static_funcs import export_concepts


def create_flask_app():
    app = Flask(__name__, instance_relative_config=True, )

    @app.route('/concept_learning', methods=['POST'])
    def concept_learning_endpoint():
        learning_problem = request.get_json(force=True)
        app.logger.debug(learning_problem)
        no_of_hypotheses = request.form.get("no_of_hypotheses", 1, type=int)
        try:
            drill_average.fit(set(learning_problem["positives"]), set(learning_problem["negatives"]))
        except Exception as e:
            app.logger.debug(e)
            abort(400)
        hypotheses: List[Node] = drill_average.best_hypotheses(no_of_hypotheses)
        file = io.BytesIO(b"")  # BytesIO has the same interface as File. So this should be fine
        export_concepts(kb, hypotheses, file)
        return Response(file.getvalue().decode('utf-8'), mimetype="application/rdf+xml")

    return app


kb = None

drill_average = None

if __name__ == '__main__':
    parser = ArgumentParser()
    # General
    parser.add_argument("--path_knowledge_base", type=str, required=True)
    parser.add_argument("--verbose", type=int, default=0)
    parser.add_argument('--num_workers', type=int, default=32, help='Number of cpus used during batching')

    # DQL related
    parser.add_argument("--path_knowledge_base_embeddings", type=str, required=True)
    parser.add_argument("--num_episode", type=int, default=2)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument('--num_of_sequential_actions', type=int, default=2)
    parser.add_argument('--pretrained_drill_avg_path', type=str, required=True, help='Provide a path of .pth file')
    args = parser.parse_args()
    kb = KnowledgeBase(args.path_knowledge_base)
    # TODO: use DrillAverage or DrillSample? What is the difference?
    drill_average = DrillAverage(pretrained_model_path=args.pretrained_drill_avg_path,
                                 num_of_sequential_actions=args.num_of_sequential_actions,
                                 knowledge_base=kb, path_of_embeddings=args.path_knowledge_base_embeddings,
                                 num_episode=args.num_episode, verbose=args.verbose,
                                 num_workers=args.num_workers)

    app = create_flask_app()
    app.run(host="0.0.0.0", port=8090, processes=1)  # processes=1 is important to avoid copying the kb
