const { runMemoryTests } = require('./backend/static/memoryTests.js');
runMemoryTests()
  .then(() => {
    process.exit(0);
  })
  .catch(err => {
    console.error(err);
    process.exit(1);
  });
