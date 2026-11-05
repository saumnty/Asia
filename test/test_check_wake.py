"""check_wake (fase J3): las partes que no necesitan micrófono ni openWakeWord."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import check_wake  # noqa: E402


def test_falsas_por_hora():
    assert check_wake.per_hour(3, 1800) == 6.0 and check_wake.per_hour(0, 0) == 0.0


def test_el_modelo_y_el_vad_de_la_linea_de_comandos():
    config = check_wake.config_for("oye_asia", 0.5)

    assert config["wake_word"] == "oye_asia" and config["wake_vad_threshold"] == 0.5
    assert check_wake.config_for(None, None)["wake_word"] == "hey_jarvis_v0.1"


def test_si_falta_algo_lo_dice(monkeypatch, capsys):
    monkeypatch.setattr(check_wake, "missing", lambda config: "Falta openwakeword: ...")
    monkeypatch.setattr(sys, "argv", ["check_wake.py", "--falsas", "1"])

    assert check_wake.main() == 2
    assert "Falta openwakeword" in capsys.readouterr().out
