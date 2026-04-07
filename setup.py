from setuptools import setup, find_packages

setup(
    name="vintage-commercials",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "yt-dlp>=2024.0.0",
        "requests>=2.31.0",
        "rich>=13.0.0",
        "click>=8.1.0",
        "flask>=3.0.0",
    ],
    include_package_data=True,
    package_data={
        "vintage_commercials": [
            "templates/*.html",
            "templates/**/*.html",
            "static/*.css",
            "static/*.js",
        ],
    },
    entry_points={
        "console_scripts": [
            "vintage-commercials=vintage_commercials.cli:main",
        ],
    },
    python_requires=">=3.10",
)
