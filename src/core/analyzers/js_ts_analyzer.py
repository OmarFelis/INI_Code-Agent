"""
Code-Agent — JavaScript & TypeScript Analyzer.
Regex-based analysis for JS/TS source files.
"""

import re
from pathlib import Path

import structlog

from src.core.analyzers.base import BaseAnalyzer
from src.models.domain import FileAnalysis, LanguageType

logger = structlog.get_logger()


class JavaScriptAnalyzer(BaseAnalyzer):
    """Analyzer for JavaScript files."""

    @property
    def language(self) -> LanguageType:
        return LanguageType.JAVASCRIPT

    @property
    def extensions(self) -> list[str]:
        return [".js", ".jsx", ".mjs"]

    def analyze_file(self, file_path: str, project_root: str = "") -> FileAnalysis:
        source = self._read_file(file_path)
        if not source:
            return self._empty(file_path, project_root)

        return FileAnalysis(
            file_path=self._relative_path(file_path, project_root),
            file_name=Path(file_path).name,
            language=self.language,
            total_lines=len(source.splitlines()),
            classes=self._extract_classes(source),
            functions=self._extract_functions(source),
            imports=self._extract_imports(source),
            decorators=[],
            api_endpoints=self._detect_endpoints(source),
            database_calls=self._detect_db_calls(source),
            external_calls=self._detect_external_calls(source),
            complexity=self._calc_complexity(source),
        )

    def _empty(self, fp: str, root: str) -> FileAnalysis:
        return FileAnalysis(
            file_path=self._relative_path(fp, root),
            file_name=Path(fp).name,
            language=self.language,
        )

    def _extract_classes(self, source: str) -> list[str]:
        return re.findall(r'class\s+(\w+)', source)

    def _extract_functions(self, source: str) -> list[str]:
        funcs = set()
        # function declarations
        funcs.update(re.findall(r'function\s+(\w+)\s*\(', source))
        # arrow / const functions
        funcs.update(re.findall(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', source))
        funcs.update(re.findall(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function', source))
        # class methods
        funcs.update(re.findall(r'^\s+(\w+)\s*\([^)]*\)\s*\{', source, re.MULTILINE))
        return list(funcs)

    def _extract_imports(self, source: str) -> list[str]:
        imports = re.findall(r"(?:import|require)\s*\(?['\"]([^'\"]+)['\"]", source)
        return imports

    def _detect_endpoints(self, source: str) -> list[dict]:
        endpoints = []
        # Express-style: app.get('/path', ...)
        for method in ("get", "post", "put", "delete", "patch"):
            for match in re.finditer(rf"\.{method}\s*\(\s*['\"]([^'\"]+)['\"]", source):
                endpoints.append({"method": method.upper(), "path": match.group(1), "handler": "express"})
        return endpoints

    def _detect_db_calls(self, source: str) -> list[dict]:
        patterns = ["mongoose", "sequelize", "knex", "prisma", "typeorm", ".query(", ".execute(", ".findOne("]
        return [{"tipo": p.strip(".(")} for p in patterns if p in source.lower()]

    def _detect_external_calls(self, source: str) -> list[dict]:
        calls = []
        if "axios" in source or "fetch(" in source:
            calls.append({"servicio": "HTTP", "import": "fetch/axios"})
        if "aws-sdk" in source or "@aws-sdk" in source:
            calls.append({"servicio": "AWS", "import": "aws-sdk"})
        return calls

    def _calc_complexity(self, source: str) -> int:
        cc = 1
        for kw in [r'\bif\s*\(', r'\bwhile\s*\(', r'\bfor\s*\(', r'\bcatch\s*\(',
                    r'\bcase\s+', r'&&', r'\|\|', r'\?\s*\w']:
            cc += len(re.findall(kw, source))
        return cc

    def get_function_details(self, file_path: str) -> list[dict]:
        """Basic extraction of functions with line numbers."""
        source = self._read_file(file_path)
        if not source:
            return []

        lines = source.splitlines()
        details = []

        # Classes
        for match in re.finditer(r'class\s+(\w+)', source):
            start = source[:match.start()].count('\n') + 1
            end = self._find_block_end_js(lines, start - 1)
            details.append({
                "name": match.group(1), "type": "CLASE", "parent": None,
                "linea_inicio": start, "linea_fin": end,
                "lineas_codigo": end - start + 1,
                "complejidad": 1, "docstring": False,
            })

        # Functions
        func_patterns = [
            r'function\s+(\w+)\s*\(',
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(',
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function',
        ]
        for pattern in func_patterns:
            for match in re.finditer(pattern, source):
                name = match.group(1)
                start = source[:match.start()].count('\n') + 1
                end = self._find_block_end_js(lines, start - 1)
                parent = None
                for d in details:
                    if d["type"] == "CLASE" and d["linea_inicio"] <= start <= d["linea_fin"]:
                        parent = d["name"]
                details.append({
                    "name": name, "type": "FUNCION", "parent": parent,
                    "linea_inicio": start, "linea_fin": end,
                    "lineas_codigo": end - start + 1,
                    "complejidad": 1, "docstring": False,
                })

        return details

    def _find_block_end_js(self, lines: list[str], start_idx: int) -> int:
        depth = 0
        found = False
        for i in range(start_idx, len(lines)):
            for ch in lines[i]:
                if ch == '{':
                    depth += 1
                    found = True
                elif ch == '}':
                    depth -= 1
                    if found and depth == 0:
                        return i + 1
        return len(lines)


class TypeScriptAnalyzer(JavaScriptAnalyzer):
    """Analyzer for TypeScript — extends JavaScript analyzer with TS-specific features."""

    @property
    def language(self) -> LanguageType:
        return LanguageType.TYPESCRIPT

    @property
    def extensions(self) -> list[str]:
        return [".ts", ".tsx"]

    def analyze_file(self, file_path: str, project_root: str = "") -> FileAnalysis:
        analysis = super().analyze_file(file_path, project_root)
        analysis.language = LanguageType.TYPESCRIPT

        # Extract TypeScript-specific: interfaces, decorators
        source = self._read_file(file_path)
        if source:
            interfaces = re.findall(r'(?:export\s+)?interface\s+(\w+)', source)
            analysis.classes.extend(interfaces)
            decorators = [f"@{d}" for d in re.findall(r'@(\w+)', source)]
            analysis.decorators = decorators

        return analysis
