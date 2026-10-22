"""Acciones de Brain agrupadas por tema.

Cada módulo define un mixin con métodos handle_<acción>(self, text, params)
y un diccionario HANDLERS {acción: nombre del método}. Brain hereda de todos
y despacha con la unión de esos diccionarios. Un handler puede devolver None
para que el mensaje se trate como conversación normal.
"""
