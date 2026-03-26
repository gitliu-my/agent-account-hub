from __future__ import annotations

from setuptools import find_packages, setup
from py2app.build_app import py2app as _py2app


class py2app(_py2app):
    def finalize_options(self) -> None:
        # py2app 0.28 rejects setuptools' install_requires metadata.
        # The build already runs inside a prepared venv, so packaging should
        # bundle the current environment instead of resolving dependencies here.
        self.distribution.install_requires = None
        super().finalize_options()


APP = ["scripts/CodexAccountHubTray.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Codex Account Hub",
        "CFBundleDisplayName": "Codex Account Hub",
        "CFBundleIdentifier": "dev.codex.accounthub",
        "LSUIElement": True,
    },
    "packages": ["rumps", *find_packages("src")],
}


setup(
    app=APP,
    cmdclass={"py2app": py2app},
    options={"py2app": OPTIONS},
    package_dir={"": "src"},
    packages=find_packages("src"),
    setup_requires=["py2app"],
)
