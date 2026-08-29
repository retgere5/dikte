"""Run the package as `python -m dikte`.

The parent of this package has to be on the path for `-m dikte` to find it,
which is what the launchers and cli.launch_gui arrange before starting it.
"""

import sys

from dikte.app import main

sys.exit(main())
