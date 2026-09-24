const apiKey = "sk_live_abcdef1234567890";

function run(userInput) {
  return eval(userInput);
}

function buildQuery(name) {
  const query = "SELECT * FROM users WHERE name = '" + name + "'";
  return query;
}

module.exports = { run, buildQuery, apiKey };
