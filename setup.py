"""Compatibility metadata for the legacy pip bundled with macOS Python 3.9."""

from setuptools import find_packages, setup


setup(
    name="raf2hncs",
    version="0.9.7",
    description="Transplant a GFX100RF Bayer mosaic into an X2D 100C 3FR donor",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=["numpy>=2.0", "scipy>=1.13,<2"],
    extras_require={
        "lens": ["opencv-python-headless>=4.10"],
        "test": ["pytest>=8,<9", "opencv-python-headless>=4.10"],
    },
    entry_points={
        "console_scripts": [
            "raf2hncs=raf2hncs.cli:main",
            "raf2hncs-web=raf2hncs.web:main",
        ]
    },
    package_data={"raf2hncs": ["web_static/*.html", "web_static/*.css", "web_static/*.js"]},
)
