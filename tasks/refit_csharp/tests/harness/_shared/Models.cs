namespace Harness;

// DTOs used by the test interfaces. Response DTOs deserialize from canned JSON; request DTOs
// serialize into the outgoing body/query.
public sealed class User
{
    public int Id { get; set; }
    public string? Name { get; set; }
}

public sealed class CreateUser
{
    public string? Name { get; set; }
    public int Age { get; set; }
}

public sealed class UserGroupRequest
{
    public int GroupId { get; set; }
    public int UserId { get; set; }
}

public enum KindOptions
{
    Foo,

    [System.Runtime.Serialization.EnumMember(Value = "bar")]
    Bar,
}

public sealed class MyQuery
{
    [Restly.AliasAs("order")]
    public string? SortOrder { get; set; }

    public int Limit { get; set; }

    public KindOptions Kind { get; set; }
}

public sealed class SnakeQuery
{
    public string? SortOrder { get; set; }

    public int PageSize { get; set; }
}

public sealed class AcroQuery
{
    // Acronym-prefixed names exercise the camelCase policy's leading-uppercase-run rule.
    public string? APIKey { get; set; }

    public int IOSize { get; set; }
}

public sealed class FormModel
{
    // No attribute -> the form field name is the CLR name verbatim (NOT camelCased).
    public string? UserName { get; set; }

    [Restly.AliasAs("years")]
    public int Age { get; set; }

    // Null -> omitted from the form body.
    public string? Note { get; set; }
}

// --- composed-workflow + edge-case models (bespoke domain) ---
public sealed class Order
{
    public int Id { get; set; }
    public string? Status { get; set; }
}

public enum Priority
{
    Low,

    [System.Runtime.Serialization.EnumMember(Value = "hi")]
    High,
}

public sealed class OrderQuery
{
    [Restly.AliasAs("sort")]
    public string? SortBy { get; set; }

    public int Limit { get; set; }

    public Priority Priority { get; set; }
}

public sealed class NewOrder
{
    public string? Sku { get; set; }

    public int Qty { get; set; }
}

public sealed class Org
{
    public string? Name { get; set; }
}

public sealed class Owner
{
    public string? Login { get; set; }

    public Org? Org { get; set; }
}

public sealed class NullableQuery
{
    [Restly.Query(SerializeNull = true)]
    public string? Note { get; set; }

    public int Count { get; set; }
}

public sealed class Address
{
    public string? City { get; set; }

    public int Zip { get; set; }
}

public sealed class DeepQuery
{
    public string? Name { get; set; }

    public Address? Address { get; set; }

    public int[]? Tags { get; set; }

    public Dictionary<string, string>? Meta { get; set; }
}
