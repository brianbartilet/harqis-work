# Add import statements for task modules so their @SPROUT.task() decorators
# run at worker startup (autodiscover only scans top-level tasks.py, not the
# tasks/ subpackage). Cross-platform safe — test_farm imports no win-only deps.
import workflows.testing.tasks.test_farm
import workflows.testing.tasks.test_farm_email
