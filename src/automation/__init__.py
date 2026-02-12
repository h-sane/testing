# automation_tree/__init__.py
"""
Automation Tree persistence layer.
Provides element fingerprinting, tree building, caching, and matching.
"""

from . import fingerprint
from . import builder
from . import storage
from . import matcher

__all__ = ['fingerprint', 'builder', 'storage', 'matcher']
