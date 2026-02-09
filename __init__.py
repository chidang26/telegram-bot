"""
Package games
Tự động register tất cả game vào bot
"""

from . import game

def register(app):
    game.register(app)
