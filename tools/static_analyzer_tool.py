import ast
from pathlib import Path

from config.settings_manager import SettingsManager
from core.paths import has_ignored_part, is_private_data


class StaticAnalyzerTool:
    name = "static_analyzer"

    def analyze_file(self, file_path: str):
        path = Path(file_path)

        if not path.exists():
            return f"No existe el archivo: {file_path}"

        lines = path.read_text(encoding="utf-8").splitlines()
        content = "\n".join(lines)
        findings = []

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return f"Error de sintaxis en {file_path}: {e}"

        for node in ast.walk(tree):
            line = getattr(node, "lineno", None)
            evidence = lines[line - 1].strip() if line else ""

            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                findings.append({
                    "line": line,
                    "risk": "Posible división entre cero",
                    "confidence": "media",
                    "evidence": evidence
                })

            if isinstance(node, ast.Subscript):
                findings.append({
                    "line": line,
                    "risk": "Posible índice fuera de rango",
                    "confidence": "media",
                    "evidence": evidence
                })

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr

                if attr in ["strip", "lower", "upper", "split"]:
                    findings.append({
                        "line": line,
                        "risk": "Posible error si el objeto es None o tipo incorrecto",
                        "confidence": "media",
                        "evidence": evidence
                    })

        if not findings:
            return "No se encontraron riesgos estáticos evidentes."

        result = f"Hallazgos estáticos en {file_path}:\n\n"

        for item in findings:
            result += (
                f"- Línea {item['line']}\n"
                f"  Riesgo: {item['risk']}\n"
                f"  Confianza: {item['confidence']}\n"
                f"  Evidencia: {item['evidence']}\n"
            )

        return result
    
    def analyze_folder(self, folder_path: str = ".", max_files: int = 30):
        path = Path(folder_path)
        reviewing_entire_project = Path(folder_path).resolve() == Path(".").resolve()

        if not path.exists():
            return f"No existe la carpeta: {folder_path}"

        supported_extensions = [
            ".py", ".m", ".c", ".cpp", ".h", ".hpp",
            ".js", ".ts", ".json", ".yaml", ".yml",
            ".sdf", ".urdf", ".launch"
        ]

        files = []

        settings = SettingsManager()
        ignored_dirs = settings.ignored_dirs()
        test_dirs = settings.test_dirs()

        # Esta misma herramienta está llena de patrones de "riesgo" a propósito.
        this_file = Path(__file__).resolve()

        for file in path.rglob("*"):

            if not file.is_file():
                continue

            if reviewing_entire_project and (
                has_ignored_part(file, path, test_dirs)
                or file.name.startswith("test_")
            ):
                continue

            if file.suffix.lower() not in supported_extensions:
                continue

            if has_ignored_part(file, path, ignored_dirs) or is_private_data(file):
                continue

            if file.resolve() == this_file:
                continue

            files.append(file)

        files = files[:max_files]

        if not files:
            return "No se encontraron archivos analizables."

        report = "Análisis estático del proyecto:\n\n"

        for file in files:
            result = self.analyze_file(str(file))

            if "No se encontraron riesgos" not in result:
                report += f"\n=== {file} ===\n"
                report += result
                report += "\n"

        if report.strip() == "Análisis estático del proyecto:":
            return "No se encontraron riesgos estáticos evidentes en el proyecto."

        return report