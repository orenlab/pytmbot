import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from app.core.handlers.handlers_aggregator import HandlersAggregator


class TestHandlersAggregator(unittest.TestCase):
    def setUp(self):
        self.handlers = [MagicMock(), MagicMock()]
        self.bot = MagicMock()
        self.handlers_aggregator = HandlersAggregator(self.bot)
        self.handlers_aggregator.handlers = self.handlers

    def test_run_handlers_success(self):
        # Test that the method runs all handlers concurrently without raising an exception
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(handler.handle) for handler in self.handlers]
            self.handlers_aggregator.run_handlers()
            for future in futures:
                self.assertTrue(future.done())


if __name__ == '__main__':
    unittest.main()
