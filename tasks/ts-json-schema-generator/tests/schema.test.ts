// Hidden test suite for ts-json-schema-generator (WRG).
// Each test drives the PUBLIC programmatic API (createGenerator().createSchema()) against a novel
// fixture with a fully-pinned config, and asserts EXACT (deepStrictEqual) equality with the
// groundtruth-generated draft-07 schema. Object-key order is irrelevant under toEqual; only array
// order (required/enum/items/allOf) is enforced.
import { test, expect } from 'vitest';
import { createGenerator } from 'ts-json-schema-generator';

const FIX = '/tests/fixtures';
function gen(file: string, type: string, extra: Record<string, unknown> = {}) {
  return createGenerator({
    path: `${FIX}/${file}.ts`, type, expose: 'export', topRef: true, jsDoc: 'extended',
    skipTypeCheck: true, additionalProperties: false, encodeRefs: true, sortProps: true,
    discriminatorType: 'json-schema', ...extra,
  }).createSchema(type);
}
const P = (s: string) => JSON.parse(s);

test('interface with nested type, optional vs required props, additionalProperties', () => {
  expect(gen('inventory', 'Inventory')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Inventory","definitions":{"Inventory":{"type":"object","properties":{"warehouse":{"type":"string"},"items":{"type":"array","items":{"$ref":"#/definitions/Item"}},"locked":{"type":"boolean"}},"required":["warehouse","items","locked"],"additionalProperties":false},"Item":{"type":"object","properties":{"sku":{"type":"string"},"qty":{"type":"number"},"note":{"type":"string"}},"required":["sku","qty"],"additionalProperties":false}}}`));
});

test('discriminated union emits if/then/allOf with const discriminator', () => {
  expect(gen('payment', 'PaymentMethod')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/PaymentMethod","definitions":{"PaymentMethod":{"type":"object","properties":{"kind":{"enum":["card","cash","wire"]}},"required":["kind"],"allOf":[{"if":{"properties":{"kind":{"type":"string","const":"card"}}},"then":{"$ref":"#/definitions/CardPayment"}},{"if":{"properties":{"kind":{"type":"string","const":"cash"}}},"then":{"$ref":"#/definitions/CashPayment"}},{"if":{"properties":{"kind":{"type":"string","const":"wire"}}},"then":{"$ref":"#/definitions/WirePayment"}}]},"CardPayment":{"type":"object","properties":{"kind":{"type":"string","const":"card"},"last4":{"type":"string"}},"required":["kind","last4"],"additionalProperties":false},"CashPayment":{"type":"object","properties":{"kind":{"type":"string","const":"cash"},"received":{"type":"number"}},"required":["kind","received"],"additionalProperties":false},"WirePayment":{"type":"object","properties":{"kind":{"type":"string","const":"wire"},"iban":{"type":"string"}},"required":["kind","iban"],"additionalProperties":false}}}`));
});

test('generic used at two instantiations produces two distinct encoded definitions', () => {
  expect(gen('wrapper', 'Holder')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Holder","definitions":{"Holder":{"type":"object","properties":{"s":{"$ref":"#/definitions/Wrapper%3Cstring%3E"},"n":{"$ref":"#/definitions/Wrapper%3Cnumber%3E"}},"required":["s","n"],"additionalProperties":false},"Wrapper<string>":{"type":"object","properties":{"value":{"type":"string"},"tag":{"type":"string"}},"required":["value","tag"],"additionalProperties":false},"Wrapper<number>":{"type":"object","properties":{"value":{"type":"number"},"tag":{"type":"string"}},"required":["value","tag"],"additionalProperties":false}}}`));
});

test('string enum becomes a named enum definition', () => {
  expect(gen('status', 'Doc')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Doc","definitions":{"Doc":{"type":"object","properties":{"id":{"type":"string"},"status":{"$ref":"#/definitions/Status"}},"required":["id","status"],"additionalProperties":false},"Status":{"type":"string","enum":["draft","live","archived"]}}}`));
});

test('JSDoc annotations map to schema keywords (minimum/maximum/format/pattern)', () => {
  expect(gen('annotated', 'Profile')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Profile","definitions":{"Profile":{"type":"object","properties":{"age":{"type":"number","minimum":0,"maximum":120},"email":{"type":"string","format":"email"},"code":{"type":"string","pattern":"^[A-Z]{3}$"}},"required":["age","email","code"],"additionalProperties":false}}}`));
});

test('labeled tuple with rest emits items array + additionalItems', () => {
  expect(gen('coords', 'Path')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Path","definitions":{"Path":{"type":"object","properties":{"name":{"type":"string"},"seg":{"$ref":"#/definitions/Segment"}},"required":["name","seg"],"additionalProperties":false},"Segment":{"type":"array","minItems":2,"items":[{"type":"number","title":"start"},{"type":"number","title":"end"}],"additionalItems":{"type":"string","title":"labels"}}}}`));
});

test('recursive type resolves to a self $ref (circular)', () => {
  expect(gen('tree', 'TreeNode')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/TreeNode","definitions":{"TreeNode":{"type":"object","properties":{"value":{"type":"number"},"children":{"type":"array","items":{"$ref":"#/definitions/TreeNode"}}},"required":["value","children"],"additionalProperties":false}}}`));
});

test('index signatures / Record become typed additionalProperties', () => {
  expect(gen('lookup', 'Registry')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Registry","definitions":{"Registry":{"type":"object","properties":{"counts":{"type":"object","additionalProperties":{"type":"number"}},"labels":{"type":"object","additionalProperties":{"type":"string"}}},"required":["counts","labels"],"additionalProperties":false}}}`));
});

test('mapped type over a literal-union key set expands to explicit properties', () => {
  expect(gen('flags', 'Perms')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Perms","definitions":{"Perms":{"type":"object","properties":{"user":{"type":"string"},"flags":{"$ref":"#/definitions/Flags"}},"required":["user","flags"],"additionalProperties":false},"Flags":{"type":"object","properties":{"read":{"type":"boolean"},"write":{"type":"boolean"},"exec":{"type":"boolean"}},"required":["read","write","exec"],"additionalProperties":false}}}`));
});

test('Partial<T> makes every property optional (no required array)', () => {
  expect(gen('partial', 'Wrap')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Wrap","definitions":{"Wrap":{"type":"object","properties":{"data":{"$ref":"#/definitions/MaybeFull"}},"required":["data"],"additionalProperties":false},"MaybeFull":{"type":"object","properties":{"a":{"type":"number"},"b":{"type":"string"},"c":{"type":"boolean"}},"additionalProperties":false}}}`));
});

test('conditional type with infer resolves per instantiation', () => {
  expect(gen('unwrap', 'Box')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Box","definitions":{"Box":{"type":"object","properties":{"a":{"$ref":"#/definitions/Unwrap%3Cnumber%3E"},"b":{"$ref":"#/definitions/Unwrap%3Cstring%3E"}},"required":["a","b"],"additionalProperties":false},"Unwrap<number>":{"type":"number"},"Unwrap<string>":{"type":"string"}}}`));
});

test('intersection merges members (required sorted)', () => {
  expect(gen('combined', 'Store')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Store","definitions":{"Store":{"type":"object","properties":{"entity":{"$ref":"#/definitions/Entity"}},"required":["entity"],"additionalProperties":false},"Entity":{"type":"object","additionalProperties":false,"properties":{"createdAt":{"type":"number"},"id":{"type":"string"}},"required":["createdAt","id"]}}}`));
});

test('keyof yields a string enum of the property names', () => {
  expect(gen('keys', 'Ref')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Ref","definitions":{"Ref":{"type":"object","properties":{"key":{"$ref":"#/definitions/ConfigKey"}},"required":["key"],"additionalProperties":false},"ConfigKey":{"type":"string","enum":["host","port","secure"]}}}`));
});

test('template literal type becomes a plain string schema', () => {
  expect(gen('route', 'Endpoint')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Endpoint","definitions":{"Endpoint":{"type":"object","properties":{"path":{"$ref":"#/definitions/Route"},"method":{"type":"string"}},"required":["path","method"],"additionalProperties":false},"Route":{"type":"string"}}}`));
});

test('numeric enum emits numeric enum values', () => {
  expect(gen('level', 'Alert')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Alert","definitions":{"Alert":{"type":"object","properties":{"name":{"type":"string"},"level":{"$ref":"#/definitions/Level"}},"required":["name","level"],"additionalProperties":false},"Level":{"type":"number","enum":[1,2,3]}}}`));
});

test('primitive union (string|number|null) becomes a type array', () => {
  expect(gen('mixed', 'Cell')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Cell","definitions":{"Cell":{"type":"object","properties":{"value":{"type":["string","number","null"]},"label":{"type":"string"}},"required":["value","label"],"additionalProperties":false}}}`));
});

test('non-discriminated object union emits anyOf of $refs', () => {
  expect(gen('pet', 'Owner')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Owner","definitions":{"Owner":{"type":"object","properties":{"pet":{"$ref":"#/definitions/Pet"},"name":{"type":"string"}},"required":["pet","name"],"additionalProperties":false},"Pet":{"anyOf":[{"$ref":"#/definitions/Dog"},{"$ref":"#/definitions/Cat"}]},"Dog":{"type":"object","properties":{"bark":{"type":"boolean"}},"required":["bark"],"additionalProperties":false},"Cat":{"type":"object","properties":{"meow":{"type":"boolean"}},"required":["meow"],"additionalProperties":false}}}`));
});

test('discriminated union with discriminatorType open-api emits oneOf + discriminator', () => {
  expect(gen('oapi', 'Pay', { discriminatorType: 'open-api' })).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Pay","definitions":{"Pay":{"type":"object","discriminator":{"propertyName":"kind"},"required":["kind"],"oneOf":[{"$ref":"#/definitions/CardPay"},{"$ref":"#/definitions/CashPay"}]},"CardPay":{"type":"object","properties":{"kind":{"type":"string","const":"card"},"last4":{"type":"string"}},"required":["kind","last4"],"additionalProperties":false},"CashPay":{"type":"object","properties":{"kind":{"type":"string","const":"cash"},"amount":{"type":"number"}},"required":["kind","amount"],"additionalProperties":false}}}`));
});

test('string-literal-union type alias becomes a named string enum', () => {
  expect(gen('palette', 'Swatch')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Swatch","definitions":{"Swatch":{"type":"object","properties":{"shade":{"$ref":"#/definitions/Shade"},"hex":{"type":"string"}},"required":["shade","hex"],"additionalProperties":false},"Shade":{"type":"string","enum":["crimson","cerulean","amber"]}}}`));
});

test('Pick<T,K> emits only the selected properties', () => {
  expect(gen('pick', 'Directory')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Directory","definitions":{"Directory":{"type":"object","properties":{"entry":{"$ref":"#/definitions/PublicMember"}},"required":["entry"],"additionalProperties":false},"PublicMember":{"type":"object","properties":{"handle":{"type":"string"},"joined":{"type":"number"}},"required":["handle","joined"],"additionalProperties":false}}}`));
});

test('Omit<T,K> emits the remaining properties', () => {
  expect(gen('omit', 'Vault')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Vault","definitions":{"Vault":{"type":"object","properties":{"safe":{"$ref":"#/definitions/SafeSecret"}},"required":["safe"],"additionalProperties":false},"SafeSecret":{"type":"object","properties":{"scope":{"type":"string"},"expiresAt":{"type":"number"}},"required":["scope","expiresAt"],"additionalProperties":false}}}`));
});

test('Record with a union value type emits typed additionalProperties', () => {
  expect(gen('ledger', 'Ledger')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Ledger","definitions":{"Ledger":{"type":"object","properties":{"entries":{"type":"object","additionalProperties":{"type":["number","string"]}}},"required":["entries"],"additionalProperties":false}}}`));
});

test('@nullable reshapes a primitive property to a null-inclusive type array', () => {
  expect(gen('nullable', 'Node2')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Node2","definitions":{"Node2":{"type":"object","properties":{"parent":{"type":["string","null"]},"label":{"type":"string"}},"required":["parent","label"],"additionalProperties":false}}}`));
});

test('indexed access type (T["key"]) resolves to the referenced member shape', () => {
  expect(gen('indexed', 'Shelf')).toEqual(P(`{"$schema":"http://json-schema.org/draft-07/schema#","$ref":"#/definitions/Shelf","definitions":{"Shelf":{"type":"object","properties":{"m":{"$ref":"#/definitions/BookMeta"}},"required":["m"],"additionalProperties":false},"BookMeta":{"type":"object","properties":{"pages":{"type":"number"},"isbn":{"type":"string"}},"required":["pages","isbn"],"additionalProperties":false}}}`));
});
