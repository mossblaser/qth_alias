from setuptools import setup, find_packages

with open("qth_alias/version.py", "r") as f:
    exec(f.read())

setup(
    name="qth_alias",
    version=__version__,
    packages=find_packages(),

    # Metadata for PyPi
    url="https://github.com/mossblaser/qth_alias",
    author="Jonathan Heathcote",
    description="Utility for creating aliases of Qth properties and events.",
    license="GPLv2",
    classifiers=[
        "Development Status :: 3 - Alpha",

        "Intended Audience :: Developers",

        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",

        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS",

        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
    ],
    keywords="mqtt asyncio home-automation messaging",

    # Requirements
    install_requires=["qth>=0.6.0", "qth_ls>=0.1.0"],

    # Scripts
    entry_points={
        "console_scripts": [
            "qth_alias = qth_alias.server:main",
        ],
    }
)
