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

from ontolearn.executor import execute
from argparse import ArgumentParser

from argparse import ArgumentParser
from argument_groups import (knowledge_graph_args, model_specific_args, 
                            evo_learner_args, nces_args)


def get_default_arguments(description=None):
    parser = ArgumentParser()

    # Model argument
    parser.add_argument("--model", type=str, default="celoe",
                        choices=["celoe", "ocel", "evolearner", "nces"],
                        help="Available concept learning models.")

    # Add knowledge graph related arguments
    for arg in knowledge_graph_args:
        parser.add_argument(arg[0], type=arg[1], default=arg[2], help=arg[3], choices=arg[4] if len(arg) > 4 else None)

    # Add model-specific arguments
    for arg in model_specific_args:
        parser.add_argument(arg[0], type=arg[1], default=arg[2], help=arg[3])

    # Add EvoLearner specific arguments
    for arg in evo_learner_args:
        parser.add_argument(arg[0], type=arg[1], default=arg[2], help=arg[3], choices=arg[4] if len(arg) > 4 else None)

    # Add NCES specific arguments
    for arg in nces_args:
        parser.add_argument(arg[0], type=arg[1], default=arg[2], help=arg[3], choices=arg[4] if len(arg) > 4 else None)

    return parser.parse_args(description) if description else parser.parse_args()


if __name__ == '__main__':
    execute(get_default_arguments())
