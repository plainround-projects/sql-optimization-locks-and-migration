"""The lesson's names: the objects its migrations create and the plans the plan-flip experiment captures."""

COLUMN = "flagged"
CHECK_CONSTRAINT = "flagged_not_null"
DEVICE_INDEX = "idx_events_device_created"
EXTENDED_STATISTICS = "events_region_city"
FLIP_PLANS = ("f1_stale_statistics", "f2_after_analyze", "f3_after_extended_statistics")
FLIP_PLAN_LABELS = {
    "f1_stale_statistics": "Before statistics catch up",
    "f2_after_analyze": "After ANALYZE",
    "f3_after_extended_statistics": "After extended statistics",
}
