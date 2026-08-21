#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署配置加载：路径与外来块定义每人每机不同，一律由配置文件提供，脚本不写死本机路径。

查找顺序：PROMPT_AUDIT_CONFIG 环境变量 > ~/.config/prompt-audit/config.yaml。
配置文件不存在时返回空 dict，各脚本退回自身的中性默认值；
sync 写真身必须知道路径，无配置时由调用方报错引导（模板在本 skill 的 config.example.yaml）。
"""

import os

import yaml

CONFIG_PATH = os.path.expanduser("~/.config/prompt-audit/config.yaml")


def load_config():
    """返回 (配置 dict, 配置文件路径)。配置文件不存在时返回 ({}, 查找路径)。"""
    path = os.environ.get("PROMPT_AUDIT_CONFIG") or CONFIG_PATH
    if not os.path.isfile(path):
        return {}, path
    with open(path, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}), path


def path_of(cfg, key, default=None):
    """取配置中的路径并展开 ~；缺省返回 default（不展开）。"""
    v = cfg.get(key, default)
    return os.path.expanduser(v) if isinstance(v, str) else v
