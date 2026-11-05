# -- Project information -----------------------------------------------------

project = 'zephyr-labgrid'
copyright = '2026, Ozan Durgut'
author = 'Ozan Durgut'
version = '0.1'
release = version

language = 'en'

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.intersphinx',
    'sphinx_copybutton',
]

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
source_suffix = '.rst'

# Copy only the commands of a console block, without the "$ " prompt.
copybutton_prompt_text = '$ '
copybutton_only_copy_prompt_lines = True

# -- External docs configuration ---------------------------------------------

intersphinx_mapping = {
    'labgrid': ('https://labgrid.readthedocs.io/en/latest', None),
    'zephyr': ('https://docs.zephyrproject.org/latest', None),
}

# -- Options for HTML output -------------------------------------------------

html_theme = 'furo'
html_title = f'zephyr-labgrid {version}'

html_theme_options = {
    'source_repository': 'https://github.com/ozan956/zephyr-labgrid/',
    'source_branch': 'main',
    'source_directory': 'docs/',
}
