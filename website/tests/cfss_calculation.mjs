// Offline calculation checks: no DOM, network, browser or customer information.
// Evaluates only the pure calculate() function extracted from the source.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const html = fs.readFileSync("website/cfss-copilot/index.html","utf8");
const start = html.indexOf("function calculate(values){");
const end = html.indexOf("function collect(){",start);
assert(start>0 && end>start,"Pure calculate() function exists");
const src = html.slice(start,end)+"\nglobalThis.out=calculate;";
const ctx={};vm.runInNewContext(src,ctx,{timeout:1000});
const calculate=ctx.out;
const test={
  budget:48000,months:12,elapsed:3,spent:9500,
  wage:20,hours:30,burden:17,other:200,onetime:450,
  altWage:22,altHours:28
};
const close=(a,b)=>assert(Math.abs(a-b)<.005,"Expected values to be approximately equal: "+a+" vs "+b);
const result=calculate(test);
assert.equal(result.monthsLeft,9);
close(result.wages,2600);
close(result.employer,442);
close(result.monthly,3242);
close(result.future,29628);
close(result.projected,39128);
close(result.variance,8872);
close(result.remaining,38500);
assert(result.alternative,"Alternative scenario returned");
assert(result.alternative.monthly>result.monthly,"Alternative projected monthly cost higher");
close(result.alternative.difference,result.alternative.projected-result.projected);
close(result.alternative.variance,48000-result.alternative.projected);
const zero=calculate({...test,months:3,elapsed:3,onetime:0,spent:9500,altWage:null,altHours:null});
assert.equal(zero.monthsLeft,0);
close(zero.future,0);
close(zero.variance,38500);
assert.equal(zero.alternative,null);
const over=calculate({...test,wage:30,hours:60,burden:30});
assert(over.variance<0,"High cost schedule shows deficit");
console.log("CFSS_CALCULATION_CHECKS_PASSED=15");
