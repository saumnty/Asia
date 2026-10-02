import ast
from pathlib import Path

from config.settings_manager import SettingsManager
from core.paths import is_private_data, iter_files


class DeadCodeTool:

    name = "dead_code"

    def detect_dead_code(
        self,
        folder_path="."
    ):

        root = Path(folder_path)

        findings = []

        ignored_dirs = SettingsManager().ignored_dirs(include_tests=True)

        python_files = []

        for file in iter_files(root, ignored_dirs):
            if file.suffix.lower() != ".py" or is_private_data(file):
                continue

            python_files.append(file)

        file_contents = {}

        for file in python_files:

            try:
                content = file.read_text(
                    encoding="utf-8"
                )

                file_contents[str(file)] = content

            except Exception:
                continue

        for file_path, content in file_contents.items():

            try:
                tree = ast.parse(content)

            except Exception:
                continue

            for node in ast.walk(tree):

                if isinstance(node, ast.FunctionDef):

                    function_name = node.name

                    references = 0

                    for other_content in file_contents.values():

                        references += other_content.count(
                            function_name
                        )

                    if references <= 1:

                        findings.append({
                            "type": "unused_function",
                            "name": function_name,
                            "file": file_path,
                            "confidence": "media"
                        })

                elif isinstance(node, ast.ClassDef):

                    class_name = node.name

                    references = 0

                    for other_content in file_contents.values():

                        references += other_content.count(
                            class_name
                        )

                    if references <= 1:

                        findings.append({
                            "type": "unused_class",
                            "name": class_name,
                            "file": file_path,
                            "confidence": "media"
                        })

        if not findings:
            return "No se encontró código muerto."

        report = []

        for item in findings:

            report.append(
                f"[{item['confidence']}] "
                f"{item['type']} -> "
                f"{item['name']} "
                f"({item['file']})"
            )

        return "\n".join(report)