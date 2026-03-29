from __future__ import annotations

import sys

from setuptools import find_packages, setup


APP = ["scripts/CodexAccountHubTray.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Agent Account Hub",
        "CFBundleDisplayName": "Agent Account Hub",
        "CFBundleIdentifier": "dev.codex.agentaccounthub",
        "LSUIElement": True,
    },
    "packages": ["rumps", *find_packages("src")],
}

cmdclass = {}
options = {}
extra_setup_kwargs = {}

# Keep normal wheel/pip installs independent from py2app. py2app is only
# required when explicitly building the macOS app bundle.
if "py2app" in sys.argv:
    from py2app.build_app import py2app as _py2app

    class py2app(_py2app):
        def finalize_options(self) -> None:
            # py2app 0.28 rejects setuptools' install_requires metadata.
            # The build already runs inside a prepared venv, so packaging should
            # bundle the current environment instead of resolving dependencies here.
            self.distribution.install_requires = None
            super().finalize_options()

    cmdclass["py2app"] = py2app
    options["py2app"] = OPTIONS
    extra_setup_kwargs["app"] = APP
    extra_setup_kwargs["setup_requires"] = ["py2app"]


setup(
    cmdclass=cmdclass,
    options=options,
    package_dir={"": "src"},
    packages=find_packages("src"),
    **extra_setup_kwargs,
)
