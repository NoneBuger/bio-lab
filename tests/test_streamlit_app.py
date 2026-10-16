from streamlit.testing.v1 import AppTest
from pathlib import Path


def test_streamlit_app_loads_without_runtime_errors() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app" / "app.py").run(timeout=30)

    assert not app.exception
    assert app.title[0].value.startswith("🧬")
