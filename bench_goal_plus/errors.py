"""Control-plane errors with user-actionable messages."""


class BenchGoalPlusError(RuntimeError):
    """Base error raised by the benchmark agent."""


class ContractError(BenchGoalPlusError):
    """A registry, runner, or campaign contract is invalid."""


class UnsupportedOperation(BenchGoalPlusError):
    """The selected runner does not implement the requested operation."""
