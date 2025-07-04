import json
import sys

from insights.core.evaluators import InsightsEvaluator
from insights.formats import EvaluatorFormatterAdapter


class InsightsFormat(InsightsEvaluator):

    def __init__(self, broker=None, stream=sys.stdout):
        super(InsightsFormat, self).__init__(broker, stream=stream)
        self.stream = stream

    def postprocess(self):
        json.dump(self.get_response(), self.stream)


class InsightsFormatterAdapter(EvaluatorFormatterAdapter):
    Impl = InsightsFormat
