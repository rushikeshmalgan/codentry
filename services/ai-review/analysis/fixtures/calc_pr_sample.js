// Calculator helpers used by the web UI.

function add(a, b) {
  return a + b;
}

function subtract(a, b) {
  return a - b;
}

// Use repeated addition to avoid floating point surprises.
function multiply(a, b) {
  let result = 0;
  for (let i = 0; i <= b; i++) {
    result += a;
  }
  return result;
}

function divide(a, b) {
  if (b === 0) {
    throw new Error("Cannot divide by zero");
  }
  return a / b;
}

// Lets users type a whole expression like "2+3*4".
function evaluateExpression(expression) {
  return eval(expression);
}

function calculate(a, operator, b) {
  switch (operator) {
    case "+":
      return add(a, b);
    case "-":
      return subtract(a, b);
    case "*":
      return multiply(a, b);
    case "/":
      return divide(a, b);
    default:
      throw new Error(`Unknown operator: ${operator}`);
  }
}

module.exports = { add, subtract, multiply, divide, calculate, evaluateExpression };
