// task helpers
function unusedHelper() {
  const leftover = 1;
  return 2;
}

function total(items) {
  let sum = 0;
  for (let i = 0; i < items.length; i++) {
    sum += items[i].price;
  }
  return sum;
}

module.exports = { total, unusedHelper };
