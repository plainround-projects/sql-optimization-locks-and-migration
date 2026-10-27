"""Named errors of the lab. Each says what went wrong in terms a reader of the lock views would use."""


class LabError(Exception):
    """Base class of every error this package raises on purpose."""


class PlanParseError(LabError):
    """A query plan did not have the lines or fields the lesson reads."""


class LockWaitTimeoutError(LabError):
    """A statement gave up waiting for a lock (lock_timeout), instead of joining the lock queue for good."""


class UnknownMigrationError(LabError):
    """A migration number the lesson does not have."""


class LessonInterruptedError(LabError):
    """The replay was asked to stop (SIGINT or SIGTERM) between two steps."""
