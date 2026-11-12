"""
Gwyddion operations and the recipes that combine them.

The organising idea: Gwyddion has 197 processing functions and almost nobody
knows what all of them do or when each is the wrong choice. So every operation
here carries its own explanation -- what it does, why it is in a recipe, and
what it costs -- as data, not as documentation someone has to go and find.

That is what makes the app usable by someone who does not already know
Gwyddion, and it is what the reporting layer quotes when it says why an image
was processed the way it was.
"""

from afm_copilot.ops.catalog import (OPERATIONS, Operation, capability_registry,
                                      get_operation)
from afm_copilot.ops.recipes import RECIPES, Recipe, get_recipe
from afm_copilot.ops.recorded import (compare_logs, describe_source, parse_log,
                                      read_log, recipe_from_log)

__all__ = ["OPERATIONS", "Operation", "get_operation", "capability_registry",
           "RECIPES", "Recipe", "get_recipe",
           "read_log", "parse_log", "recipe_from_log", "describe_source"]
