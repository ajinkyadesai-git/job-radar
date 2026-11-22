// Two features pdf.js uses that older iPhones (Safari before 17.4 / before stream async
// iteration) lack, and that its "legacy" build doesn't add. Loaded before pdf.js, in the page
// and in the PDF worker. Each is added only when missing.

type Resolvers<T> = {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: unknown) => void;
};

const P = Promise as unknown as { withResolvers?: <T>() => Resolvers<T> };
if (typeof P.withResolvers !== "function") {
  P.withResolvers = function withResolvers<T>(): Resolvers<T> {
    let resolve!: Resolvers<T>["resolve"];
    let reject!: Resolvers<T>["reject"];
    const promise = new Promise<T>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  };
}

if (typeof ReadableStream !== "undefined" && !(Symbol.asyncIterator in ReadableStream.prototype)) {
  const proto = ReadableStream.prototype as unknown as Record<symbol, unknown>;
  proto[Symbol.asyncIterator] = async function* streamIterator(this: ReadableStream) {
    const reader = this.getReader();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) return;
        yield value;
      }
    } finally {
      reader.releaseLock();
    }
  };
}

export {};
