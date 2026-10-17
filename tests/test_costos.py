"""El costo del trabajo: cuánto se estima antes de arrancar y cuánto se gastó de verdad.

Esta pieza existe por la devolución de la pre-entrega 7: la regla de costo del HITL estaba escrita
pero nunca se activaba, porque `costo_estimado` llegaba siempre vacío y nadie lo calculaba. El
README la describía como si funcionara, que es la parte que no se puede repetir.

Acá está lo mínimo para que la regla sea real: una tabla de precios por modelo (pisable por
entorno), la estimación del pedido antes de correr y el costo de lo que realmente se gastó, leído
del uso que reporta el modelo.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from intelligence.graph import costos


def test_la_tabla_tiene_los_modelos_que_el_sistema_usa_por_defecto():
    for modelo in ("gemini-flash-latest", "gpt-4o-mini", "claude-3-5-sonnet-latest"):
        assert modelo in costos.PRECIOS_POR_MILLON
        entrada, salida = costos.PRECIOS_POR_MILLON[modelo]
        assert entrada >= 0 and salida >= 0


def test_la_estimacion_crece_con_el_pedido():
    corta = costos.estimar_costo("Resumí la política de vacaciones")["costo"]
    larga = costos.estimar_costo("Resumí la política de vacaciones " * 80)["costo"]
    assert corta > 0
    assert larga > corta


def test_la_estimacion_dice_de_donde_salen_los_numeros():
    detalle = costos.estimar_costo("¿Cuántos días de licencia me corresponden?", modelo="gpt-4o-mini")
    assert detalle["modelo"] == "gpt-4o-mini"
    assert detalle["tokens_entrada"] > 0
    assert detalle["tokens_salida"] > 0
    assert detalle["rondas"] >= 1
    assert detalle["costo"] == pytest.approx(
        detalle["tokens_entrada"] / 1_000_000 * detalle["precio_entrada"]
        + detalle["tokens_salida"] / 1_000_000 * detalle["precio_salida"],
        rel=1e-9,
    )


def test_un_modelo_desconocido_no_inventa_un_precio(monkeypatch):
    """No se estima un costo que no se puede saber: cero y con el motivo a la vista."""

    monkeypatch.delenv("PRECIO_ENTRADA_POR_MILLON", raising=False)
    monkeypatch.delenv("PRECIO_SALIDA_POR_MILLON", raising=False)
    detalle = costos.estimar_costo("una pregunta", modelo="modelo-que-no-existe")
    assert detalle["costo"] == 0.0
    assert detalle["precio_entrada"] == 0.0


def test_el_precio_se_puede_fijar_por_entorno(monkeypatch):
    monkeypatch.setenv("PRECIO_ENTRADA_POR_MILLON", "10")
    monkeypatch.setenv("PRECIO_SALIDA_POR_MILLON", "20")
    detalle = costos.estimar_costo("una pregunta", modelo="modelo-que-no-existe")
    assert detalle["precio_entrada"] == 10.0
    assert detalle["costo"] > 0


def test_un_precio_vacio_en_el_entorno_no_rompe_la_estimacion(monkeypatch):
    """Un `.env` copiado del `.env.example` deja las dos claves vacías, no ausentes."""

    monkeypatch.setenv("PRECIO_ENTRADA_POR_MILLON", "")
    monkeypatch.setenv("PRECIO_SALIDA_POR_MILLON", "")
    detalle = costos.estimar_costo("¿Cuántos días de licencia me corresponden?")
    assert detalle["precio_entrada"] > 0  # cae en la tabla del modelo
    assert detalle["costo"] > 0


def test_el_costo_del_modelo_configurado_no_es_cero():
    """El modelo por defecto del sistema tiene precio publicado: la estimación no puede dar 0."""

    detalle = costos.estimar_costo("¿Cuántos días de licencia anual me corresponden?")
    assert detalle["modelo"] == costos.modelo_configurado()
    assert detalle["costo"] > 0


def test_el_costo_de_una_respuesta_sale_del_uso_que_reporta_el_modelo():
    mensaje = AIMessage(
        content="listo",
        usage_metadata={"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000},
    )
    gastado = costos.costo_de_mensaje(mensaje, modelo="gemini-flash-latest")
    assert gastado == pytest.approx(1000 / 1_000_000 * 0.30 + 1000 / 1_000_000 * 2.50, rel=1e-9)


def test_un_mensaje_sin_uso_reportado_no_rompe_la_cuenta():
    """Varios proveedores no reportan tokens: se cuenta cero en vez de explotar."""

    assert costos.costo_de_mensaje(AIMessage(content="sin uso"), modelo="gemini-flash-latest") == 0.0
