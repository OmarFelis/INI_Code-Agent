"""
Code-Agent — Java Analyzer.
Regex-based analysis for Java source files.
Note: For production, consider using JavaParser via subprocess or py4j.
"""

import re
from pathlib import Path

import structlog

from src.core.analyzers.base import BaseAnalyzer
from src.models.domain import FileAnalysis, LanguageType

logger = structlog.get_logger()

# Infrastructure imports for Java
JAVA_INFRA_IMPORTS = {
    "java.sql", "javax.sql", "org.hibernate", "javax.persistence",
    "jakarta.persistence", "org.springframework.data",
    "com.amazonaws", "software.amazon",
    "org.springframework.web", "javax.servlet", "jakarta.servlet",
    "org.springframework.kafka", "org.springframework.jms",
}


class JavaAnalyzer(BaseAnalyzer):
    """Analyzer for Java source files using regex patterns."""

    @property
    def language(self) -> LanguageType:
        return LanguageType.JAVA

    @property
    def extensions(self) -> list[str]:
        return [".java"]

    def analyze_file(self, file_path: str, project_root: str = "") -> FileAnalysis:
        source = self._read_file(file_path)
        if not source:
            return self._empty(file_path, project_root)

        lines = source.splitlines()

        return FileAnalysis(
            file_path=self._relative_path(file_path, project_root),
            file_name=Path(file_path).name,
            language=LanguageType.JAVA,
            total_lines=len(lines),
            classes=self._extract_classes(source),
            functions=self._extract_methods(source),
            imports=self._extract_imports(source),
            decorators=self._extract_annotations(source),
            api_endpoints=self._detect_endpoints(source),
            database_calls=self._detect_db_calls(source),
            external_calls=self._detect_external_calls(source),
            complexity=self._calc_complexity(source),
        )

    def _empty(self, fp: str, root: str) -> FileAnalysis:
        return FileAnalysis(
            file_path=self._relative_path(fp, root),
            file_name=Path(fp).name,
            language=LanguageType.JAVA,
        )

    def _extract_classes(self, source: str) -> list[str]:
        return re.findall(r'(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)', source)

    def _extract_methods(self, source: str) -> list[str]:
        classes = self._extract_classes(source)
        methods = re.findall(
            r'(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\(',
            source
        )
        # Try to associate methods with their enclosing class
        if len(classes) == 1:
            return [f"{classes[0]}.{m}" for m in methods if m not in classes]
        return methods

    def _extract_imports(self, source: str) -> list[str]:
        return re.findall(r'import\s+([\w.]+);', source)

    def _extract_annotations(self, source: str) -> list[str]:
        return [f"@{a}" for a in re.findall(r'@(\w+)', source)]

    def _detect_endpoints(self, source: str) -> list[dict]:
        endpoints = []
        for method in ("GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping"):
            for match in re.finditer(rf'@{method}\s*\(\s*["\']([^"\']*)["\']', source):
                endpoints.append({
                    "method": method.replace("Mapping", "").upper(),
                    "path": match.group(1),
                    "handler": "detected",
                })
        # @RequestMapping
        for match in re.finditer(r'@RequestMapping\s*\(.*?method\s*=\s*RequestMethod\.(\w+).*?value\s*=\s*["\']([^"\']*)', source, re.DOTALL):
            endpoints.append({"method": match.group(1), "path": match.group(2), "handler": "detected"})
        return endpoints

    def _detect_db_calls(self, source: str) -> list[dict]:
        patterns = ["executeQuery", "executeUpdate", "createQuery", "persist", "merge",
                     "findBy", "save", "deleteBy", "JpaRepository", "CrudRepository"]
        return [{"tipo": p, "detected_by": "pattern"} for p in patterns if p in source]

    def _detect_external_calls(self, source: str) -> list[dict]:
        calls = []
        imports = self._extract_imports(source)
        for imp in imports:
            if any(infra in imp for infra in ("com.amazonaws", "software.amazon")):
                calls.append({"servicio": "AWS", "import": imp})
            elif "RestTemplate" in source or "WebClient" in source:
                calls.append({"servicio": "HTTP", "import": imp})
        return calls

    def _calc_complexity(self, source: str) -> int:
        cc = 1
        decision_keywords = [r'\bif\s*\(', r'\bwhile\s*\(', r'\bfor\s*\(',
                             r'\bcatch\s*\(', r'\bcase\s+', r'&&', r'\|\|']
        for kw in decision_keywords:
            cc += len(re.findall(kw, source))
        return cc

    def get_function_details(self, file_path: str) -> list[dict]:
        """Regex-based extraction of classes and methods with line numbers."""
        source = self._read_file(file_path)
        if not source:
            return []

        lines = source.splitlines()
        details = []

        # Find classes
        for match in re.finditer(r'(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)', source):
            class_name = match.group(1)
            start_line = source[:match.start()].count('\n') + 1
            # Find class end (matching braces)
            end_line = self._find_block_end(lines, start_line - 1)
            details.append({
                "name": class_name,
                "type": "CLASE",
                "parent": None,
                "linea_inicio": start_line,
                "linea_fin": end_line,
                "lineas_codigo": end_line - start_line + 1,
                "complejidad": self._method_complexity_range(source, start_line, end_line),
                "docstring": False,
            })

        # Find methods
        method_pattern = r'(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\('
        classes = self._extract_classes(source)
        for match in re.finditer(method_pattern, source):
            name = match.group(1)
            if name in classes:
                continue
            start_line = source[:match.start()].count('\n') + 1
            end_line = self._find_block_end(lines, start_line - 1)
            # Determine parent class
            parent = None
            for d in details:
                if d["type"] == "CLASE" and d["linea_inicio"] <= start_line <= d["linea_fin"]:
                    parent = d["name"]
            details.append({
                "name": name,
                "type": "FUNCION",
                "parent": parent,
                "linea_inicio": start_line,
                "linea_fin": end_line,
                "lineas_codigo": end_line - start_line + 1,
                "complejidad": self._method_complexity_range(source, start_line, end_line),
                "docstring": False,
            })

        return details

    def _find_block_end(self, lines: list[str], start_idx: int) -> int:
        """Find the closing brace of a block starting at start_idx."""
        depth = 0
        found_open = False
        for i in range(start_idx, len(lines)):
            for ch in lines[i]:
                if ch == '{':
                    depth += 1
                    found_open = True
                elif ch == '}':
                    depth -= 1
                    if found_open and depth == 0:
                        return i + 1  # 1-indexed
        return len(lines)

    def _method_complexity_range(self, source: str, start: int, end: int) -> int:
        """Calculate CC for a range of lines."""
        lines = source.splitlines()[start - 1:end]
        block = '\n'.join(lines)
        cc = 1
        for kw in [r'\bif\s*\(', r'\bwhile\s*\(', r'\bfor\s*\(', r'\bcatch\s*\(', r'\bcase\s+', r'&&', r'\|\|']:
            cc += len(re.findall(kw, block))
        return cc
