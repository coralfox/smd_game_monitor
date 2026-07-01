#!python3.13
"""游戏监控启动器 - 双击无窗口启动GUI"""
import os
import sys

# 切换到脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

# 直接导入并运行GUI
import game_monitor_gui
game_monitor_gui.main()
