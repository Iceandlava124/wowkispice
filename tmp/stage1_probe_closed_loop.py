import sys
sys.path.insert(0, ".")
from ui.schematic_editor import SchematicEditor
import inspect
src = inspect.getsource(SchematicEditor.run_closed_loop)
print(src)
