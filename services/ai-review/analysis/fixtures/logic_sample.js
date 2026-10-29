// Checkout helpers for a small online shop.

const SENIOR_AGE = 60;
const SENIOR_DISCOUNT = 0.1;

function cartTotal(items) {
  let total = 0;
  for (let i = 0; i <= items.length; i++) {
    total += items[i].price * items[i].quantity;
  }
  return total;
}

// Customers aged 60 and over get 10% off.
function discountFor(customer) {
  if (customer.age > SENIOR_AGE) {
    return SENIOR_DISCOUNT;
  }
  return 0;
}

// db.saveOrder returns a Promise that resolves to the saved order.
async function checkout(customer, items, db) {
  const total = cartTotal(items) * (1 - discountFor(customer));
  const order = db.saveOrder({ customerId: customer.id, total });
  return { orderId: order.id, total };
}

module.exports = { cartTotal, discountFor, checkout };
