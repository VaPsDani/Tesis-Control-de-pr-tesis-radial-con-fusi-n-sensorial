"""
Numero de parametros del modelo con 8 y 11 canales de entrada.

Solo la primera Conv1D depende de los canales C: 3 x C x 64 + 64 pesos.
Si esto cambia, cambio la arquitectura: no ajustar el test, revisar.
"""
import pytest

pytest.importorskip("tensorflow")

from modelo import construir_modelo                     # noqa: E402


@pytest.mark.parametrize("canales,esperado", [(8, 76933), (11, 77509)])
def test_parametros_con_8_y_11_canales(canales, esperado):
    m = construir_modelo(window_size=20, num_features=canales)
    assert m.input_shape == (None, 20, canales)
    assert m.count_params() == esperado
