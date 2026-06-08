"""Setup script for reddit2shorts package."""
from setuptools import setup, find_packages

# Read requirements from requirements.txt
with open("requirements.txt") as f:
    requirements = [
        line.strip() 
        for line in f 
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="reddit2shorts",
    version="0.1.0",
    description="Automated video creation from Reddit stories and images",
    author="Your Name",
    packages=find_packages(exclude=["tests", "tests.*", "examples", "examples.*"]),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "reddit2shorts=reddit2shorts.cli:main",
        ],
    },
    python_requires=">=3.12",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
)
