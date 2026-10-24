"""
    Helper that will return True/False if the function is only a forwarded function
    Also could help us to know the deep of the function.

    Example: return true if the function looks like
    def do_something(a,b):
        return do_something_else(a+b)

    Return false 
    def price_for(self, price, is_premium):
        execute_function(price)
        another_function(price)
        return self._facade.discount(price, is_premium)
"""
import ast

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class NotAForwarder(Exception):
    """Raised when a function does more than forward its arguments to one call."""


class ThinBodyClassifier:
    def is_thin(self, function: FunctionNode) -> bool:
        try:
            self.forwarded_call(function)
        except NotAForwarder:
            return False
        return True

    def forwarded_call(self, function: FunctionNode) -> ast.Call:
        statement = self._only_statement(function)
        call = self._call_of(statement)
        parameter_names = self._parameter_names(function)
        for argument in self._arguments_of(call):
            if not self._is_forwardable(argument, parameter_names):
                raise NotAForwarder("an argument is computed, not passed through")
        return call

    def _only_statement(self, function: FunctionNode) -> ast.stmt:
        statements = [s for s in function.body if not self._is_docstring(s)]
        if len(statements) != 1:
            raise NotAForwarder("body is not a single statement")
        return statements[0]

    def _is_docstring(self, statement: ast.stmt) -> bool:
        return isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)

    def _call_of(self, statement: ast.stmt) -> ast.Call:
        if not isinstance(statement, (ast.Return, ast.Expr)):
            raise NotAForwarder("statement is not a return or a bare call")
        value = statement.value
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call):
            raise NotAForwarder("statement does not call anything")
        return value

    def _parameter_names(self, function: FunctionNode) -> set[str]:
        arguments = function.args
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        parameters += [p for p in (arguments.vararg, arguments.kwarg) if p is not None]
        return {parameter.arg for parameter in parameters}

    def _arguments_of(self, call: ast.Call) -> list[ast.expr]:
        return [*call.args, *(keyword.value for keyword in call.keywords)]

    def _is_forwardable(self, argument: ast.expr, parameter_names: set[str]) -> bool:
        if isinstance(argument, ast.Starred):
            argument = argument.value
        if isinstance(argument, ast.Constant):
            return True
        return isinstance(argument, ast.Name) and argument.id in parameter_names
