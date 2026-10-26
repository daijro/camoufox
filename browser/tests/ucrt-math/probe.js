// Math results a page reads, for the windows-crt-math guard and its Windows
// reference. `input` is {trig: [hex bits], pow: [[hex, hex]]}. Each function is
// run cold, then hot enough for the JITs to compile it (they call the same
// native code, but through different paths), plus constant arguments the
// optimizer may fold at compile time.
(input) => {
  const f64 = new Float64Array(1);
  const u64 = new BigUint64Array(f64.buffer);
  const num = (h) => { u64[0] = BigInt("0x" + h); return f64[0]; };
  const hex = (v) => { f64[0] = v; return u64[0].toString(16); };
  const xs = input.trig.map(num);
  const ps = input.pow.map(([a, b]) => [num(a), num(b)]);

  const pass = () => ({
    sin: xs.map((x) => hex(Math.sin(x))),
    cos: xs.map((x) => hex(Math.cos(x))),
    tan: xs.map((x) => hex(Math.tan(x))),
    pow: ps.map(([a, b]) => hex(Math.pow(a, b))),
    exp: ps.map(([a, b]) => hex(a ** b)),
  });
  const cold = pass();
  let hot;
  for (let i = 0; i < 30; i++) {
    hot = pass();
  }
  const folded = () => [Math.sin(1e10), Math.cos(10.5), Math.tan(1e300), Math.pow(Math.PI, -100.5),
                        Math.cos(1e15), 1.8569892451203387 ** 0.75];
  let constants;
  for (let i = 0; i < 20000; i++) {
    constants = folded();
  }
  return { cold, hot, constants: constants.map(hex) };
}
