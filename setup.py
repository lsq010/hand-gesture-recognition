"""Hand Gesture Recognition System package setup."""

from setuptools import setup, find_packages

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

with open("requirements.txt", encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="hand-gesture-recognition",
    version="1.0.0",
    description="基于 MediaPipe 的实时手势识别系统（GUI 版）",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="lsq010",
    url="https://github.com/lsq010/hand-gesture-recognition",
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    install_requires=requirements,
    python_requires=">=3.9",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Multimedia :: Video :: Capture",
    ],
    entry_points={
        "console_scripts": [
            "gesture-recognition=main:main",
        ],
    },
)
