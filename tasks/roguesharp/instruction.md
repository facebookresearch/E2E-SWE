# RogueSharp

A C# toolkit for building roguelike games. It provides grid maps, field-of-view, pathfinding, goal/utility maps, dice notation parsing, procedural map generators, random number helpers, and graph algorithms.

## Build

- Target: **net8.0**
- No third-party dependencies, only the .NET BCL
- Root namespace: `RogueSharp`
- Build: `dotnet build`

## Namespaces

- `RogueSharp` – Core: Map, Cell, Path, PathFinder, DijkstraPathFinder, FieldOfView, GoalMap, Point, Rectangle
- `RogueSharp.Algorithms` – Graph utilities: Graph, UnionFind, IndexMinPriorityQueue, EdgeWeightedDigraph, DirectedEdge, DijkstraShortestPath
- `RogueSharp.DiceNotation` – Dice engine: Dice, DiceExpression, DiceResult, TermResult, plus Terms and Exceptions sub-namespaces
- `RogueSharp.MapCreation` – Map generators: IMapCreationStrategy and Border, Cave, RandomRooms, StringDeserialize implementations
- `RogueSharp.Random` – RNG: IRandom, DotNetRandom, GaussianRandom, KnownSeriesRandom, MinRandom, MaxRandom, WeightedPool, RandomState, Singleton

---

## Map Core

### ICell / Cell

`ICell : IEquatable<ICell>` exposes `int X`, `int Y`, `bool IsTransparent`, `bool IsWalkable`, all read/write.

`Cell : ICell`. Default ctor and `Cell(x, y, isTransparent, isWalkable)`. Equality is by X/Y only. Supports `==` / `!=`.

`Cell.ToString()`:
- `.` transparent and walkable
- `s` walkable only
- `o` transparent only
- `#` neither

### Map

`Map<TCell> where TCell : ICell` holds the full implementation. `Map : Map<Cell>, IMap` is the usual concrete type.

Construction:
- `Map()` – uninitialized, call `Initialize(width, height)` first. Cells start non-transparent, non-walkable.
- `Map(width, height)` – initializes immediately.

Factory: `Map.Create<TMap>(IMapCreationStrategy<TMap> strategy)`

Cell access:
- `GetCell(x, y)`, `SetCellProperties(x, y, isTransparent, isWalkable)`
- `IsTransparent(x, y)`, `IsWalkable(x, y)`
- `Clear(isTransparent, isWalkable)` – set the whole map; parameterless `Clear()` resets to false/false
- Indexer `map[x, y]`

Geometry queries, all `IEnumerable<Cell>`:
- `GetAllCells()` – row-major
- `GetAdjacentCells(x, y)` – 4-way; overload with `includeDiagonals` gives up to 8-way
- `GetCellsAlongLine(x0,y0,x1,y1)` – Bresenham, destination clamped to map bounds
- `GetCellsInCircle(xCenter, yCenter, radius)` – filled, midpoint circle, unique in-bounds cells only
- `GetCellsInDiamond` – Manhattan distance
- `GetCellsInSquare` – Chebyshev distance
- `GetCellsInRectangle(top, left, width, height)`
- `GetBorderCellsInCircle/Diamond/Square` – perimeter only
- `GetCellsInRows(params int[])`, `GetCellsInColumns(params int[])`

Indexing:
- `IndexFor(x, y) = y * Width + x`
- `IndexFor(Cell)`, `CellFor(index)`

Serialization:
- `ToString()` – map as `. s o #` rows joined by `Environment.NewLine`
- `Save()` → `MapState`, `Restore(MapState)`

Copying:
- `Clone<TMap>()` – deep copy
- `Copy(sourceMap, left, top)` – blit source into this map; overload without coordinates copies at (0,0)

### MapState

Plain DTO: `int Width`, `int Height`, `CellProperties[] Cells`

`[Flags] enum CellProperties { None=0, Walkable=1, Transparent=2 }`

---

## Map Creation Strategies

Each concrete strategy is itself generic in the map type it produces: `XxxMapCreationStrategy<TMap> : IMapCreationStrategy<TMap>` with `TMap CreateMap()`, where `TMap` is a default-constructible map type (`Map` in ordinary use). Used via `Map.Create(strategy)`.

- **BorderOnlyMapCreationStrategy<TMap>(width, height)** – solid outer walls, interior fully transparent/walkable
- **StringDeserializeMapCreationStrategy<TMap>(mapRepresentation)** – rebuild a map from `. s o #` text, lines split on newline, leading whitespace per line is trimmed
- **CaveMapCreationStrategy<TMap>(width, height, fillProbability, totalIterations, cutoffOfBigAreaFill, random)** – cellular-automata caves. `fillProbability` 0-100 initial density, `totalIterations` smoothing passes, `cutoffOfBigAreaFill` switches neighbor-count rule. Borders are always walls. Deterministic with a given `IRandom`
- **RandomRoomsMapCreationStrategy<TMap>(width, height, maxRooms, roomMaxSize, roomMinSize, random)** – scatter non-overlapping axis-aligned rooms on a walled map. Deterministic with a given `IRandom`

---

## Field of View

`FieldOfView`, recursive shadowcasting.

- `new FieldOfView(map)`
- `ComputeFov(x, y, radius, lightWalls)` – `lightWalls=true` includes blocking cells at the vision edge. Returns the newly visible cells as `ReadOnlyCollection<Cell>`
- `AppendFov(x, y, radius, lightWalls)` – additive, for multiple light sources. Returns the full combined visible set
- `IsInFov(x, y)`
- `Clone()`

Opaque cells block sight behind them.

---

## Pathfinding

### PathFinder – A*

- `new PathFinder(map)` – 4-way, cost 1.0
- `new PathFinder(map, diagonalCost)` – 8-way, e.g. 1.41
- `ShortestPath(source, destination)` – throws `PathNotFoundException` if unreachable
- `TryFindShortestPath(source, destination)` – returns `null` if unreachable or source is not walkable

Only `IsWalkable` cells are traversable. Diagonal moves are unrestricted: an 8-way move to a walkable diagonal neighbor is always allowed, even when one or both of the orthogonally-adjacent cells it passes between are walls (corner-cutting is permitted). The same corner-cutting rule applies to `DijkstraPathFinder` and to `GoalMap` when diagonal movement is enabled.

### DijkstraPathFinder

Same surface as PathFinder, Dijkstra-based:
- `new DijkstraPathFinder(map)` / `new DijkstraPathFinder(map, diagonalCost)`
- `ShortestPath(Cell source, Cell destination)` / `TryFindShortestPath(Cell source, Cell destination)` – note `Cell`, not `ICell`

### Path

Ordered cell sequence from start to end.

- `new Path(IEnumerable<ICell> steps)`
- `Length`, `Start`, `End`, `CurrentStep`
- `StepForward()` / `TryStepForward()` – throws `NoMoreStepsException` / returns `null` at the end
- `StepBackward()` / `TryStepBackward()`
- `Steps : IEnumerable<ICell>`

Exceptions:
- `PathNotFoundException`
- `NoMoreStepsException`
Both with `()`, `(message)`, `(message, inner)` ctors.

---

## Goal Maps

Dijkstra desire maps for AI. Lower weight = more attractive.

- `new GoalMap(map)` / `new GoalMap(map, allowDiagonalMovement)`
- `AddGoal(x, y, weight)` – weight 0 is most attractive
- `RemoveGoal(x, y)`, `ClearGoals()`
- `AddObstacle(x, y)`, `AddObstacles(IEnumerable<Point>)`
- `RemoveObstacle(x, y)`, `ClearObstacles()`
- `FindPath(x, y)` – toward nearest goal, throws `PathNotFoundException` if none
- `TryFindPath(x, y)` – returns `null` instead
- `FindPaths(x, y)` – all equally good paths, `ReadOnlyCollection<Path>`
- `TryFindPaths(x, y)` – empty collection if none
- `FindPathAvoidingGoals(x, y)` – flee mode, inverts weights by -1.2, throws if boxed in
- `TryFindPathAvoidingGoals(x, y)` – returns `null` if no escape

Obstacles are non-traversable, including as a starting point: a path or flee query whose origin cell `(x, y)` is itself an obstacle — or a non-walkable map cell — has no path from it.

---

## Dice Notation

### Dice

Static facade:
- `Dice.Parse(expression)` → `DiceExpression`, `ArgumentException` on illegal characters
- `Dice.Roll(expression, random)` / `Dice.Roll(expression)` – parse and roll, int result

Supported:
- `3d6`, `3d6+5` → ToString `"3d6 + 5"`
- `4d6k3` – roll 4, keep highest 3
- `2 + -2*1d6`
- Shorthand: `d6` = `1d6`, `2 + 2*d6` normalizes to `2 + 2*1d6`

### DiceExpression

Fluent builder, also the parse result:
- `Dice(multiplicity, sides, scalar, choose)`
- `Constant(value)`
- `Roll(random)` / `Roll()` → `DiceResult`
- `MinRoll()` / `MaxRoll()`
- `ToString()` – terms joined by ` + `

### DiceResult

- `int Value`
- `ReadOnlyCollection<TermResult> Results`
- `IRandom RandomUsed`

### TermResult

`int Scalar`, `int Value`, `string TermType`

### Terms

`IDiceExpressionTerm` with `GetResults(random)` / `GetResults()`

- `DiceTerm(multiplicity, sides, choose, scalar)` – `choose` keeps top N. ToString: `[scalar*]multiplicity d sides [kchoose]`
- `ConstantTerm(constant)`

### Exceptions

`ImpossibleDieException`, `InvalidChooseException`, `InvalidMultiplicityException`, standard ctors.

---

## Random Number System

### IRandom

**`Next(minValue, maxValue)` is inclusive on both ends**, unlike `System.Random`.

- `Next(maxValue)` → [0, maxValue]
- `Next(minValue, maxValue)` → [minValue, maxValue]
- `Save()` → `RandomState`
- `Restore(RandomState)`

### RandomState

`int[] Seed`, `long NumberGenerated`

### DotNetRandom

Wraps `System.Random`, calls `Next(min, max+1)` internally.

- `DotNetRandom()` – seeds with `Environment.TickCount`
- `DotNetRandom(int seed)`
- Save/Restore replays from the seed

### GaussianRandom

Box-Muller, clamped to [min,max]. Save/Restore supported.

- `GaussianRandom()` – seeds with `Environment.TickCount`
- `GaussianRandom(int seed)`

### KnownSeriesRandom

Test helper, cycles a fixed sequence.

- `KnownSeriesRandom(params int[] series)`
- Throws `ArgumentOutOfRangeException` if the next value is outside [min,max]
- Save/Restore preserves queue position

### MinRandom / MaxRandom

Always return min / max. Used by `MinRoll()` / `MaxRoll()`.

### Singleton

`public static readonly DotNetRandom DefaultRandom`

### WeightedPool<T>

- `WeightedPool()` / `WeightedPool(random, cloneFunc)`
- `Add(item, weight)` – weight > 0
- `Draw()` – weighted random pick with probability proportional to weight, considering items in the order added; removes and returns the item, throws `InvalidOperationException` if empty
- `Choose()` – weighted pick, keeps item, returns a clone (requires cloneFunc)
- `Clear()`, `int Count`

---

## Geometry

### Point

struct, `IEquatable<Point>`

- `Point(x, y)`, `Point(value)` sets both
- `Point.Zero`
- Operators `+ - * / == !=`, component-wise, with static `Add/Subtract/Multiply/Divide/Negate`
- `Distance(a, b)` – Euclidean
- `ToString()` → `"{X:3 Y:4}"`

### Rectangle

struct, `IEquatable<Rectangle>`

- `Rectangle(x, y, width, height)`, `Rectangle(location, size)`
- `X,Y,Width,Height` rw; `Left`, `Right=X+Width`, `Top`, `Bottom=Y+Height`, `Center`, `Location`, `IsEmpty`
- `Rectangle.Empty`
- `Contains(x, y)` / `Contains(Point)` / `Contains(Rectangle)` – right/bottom exclusive
- `Intersects(other)`
- `Intersect(a, b)`, `Union(a, b)`
- `Offset(x, y)` / `Offset(Point)`
- `Inflate(horizontal, vertical)`
- `==`, `!=`

---

## Graph Algorithms

### Graph – undirected

- `Graph(vertices)`
- `NumberOfVertices`, `NumberOfEdges`
- `AddEdge(v, w)`
- `Adjacent(v) : IEnumerable<int>`

### UnionFind

Weighted quick-union with path compression.

- `UnionFind(count)` – create `count` isolated single-element sets (sites `0..count-1`)
- `int Count` – the number of disjoint sets (components)
- `Find(p)`, `Connected(p, q)`, `Union(p, q)`

### IndexMinPriorityQueue<T> where T : IComparable<T>

- `IndexMinPriorityQueue(maxSize)`
- `Size`, `IsEmpty()`, `Contains(i)`
- `Insert(index, key)`
- `MinIndex()`, `MinKey()`, `DeleteMin()`
- `KeyAt(index)`, `ChangeKey/DecreaseKey/IncreaseKey`
- `Delete(index)`

### EdgeWeightedDigraph

- `EdgeWeightedDigraph(vertices)`
- `NumberOfVertices`, `NumberOfEdges`
- `AddEdge(DirectedEdge)`
- `Adjacent(v) : IEnumerable<DirectedEdge>`
- `Edges()`, `OutDegree(v)`

### DirectedEdge

- `DirectedEdge(from, to, weight)`
- `From`, `To`, `Weight`

### DijkstraShortestPath

- `DijkstraShortestPath(graph, source)`
- `DistanceTo(v)` – `double.PositiveInfinity` if unreachable
- `HasPathTo(v)`
- `PathTo(v) : IEnumerable<DirectedEdge>`
- `FindPath(graph, source, dest)` – static helper
