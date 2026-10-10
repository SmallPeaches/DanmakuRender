"""DMR 的模块级测试包。

运行方式（仓库根目录，零额外依赖）::

    python -B -m unittest discover -s unit_tests -t . -v

或在装了 pytest 的环境里::

    python -m pytest unit_tests -v

⚠️ 目录名不要改回 ``tests/``：根 ``.gitignore`` 的 ``/test**`` 会匹配它，导致测试
对 git 不可见且会被 ``git clean`` 删除。详见 ``README.md``。
"""
