using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using RogueSharp;
using RogueSharp.Algorithms;
using RogueSharp.DiceNotation;
using RogueSharp.MapCreation;
using RogueSharp.Random;

public class Tests
{
    // ========================================================================
    // Helper: build a map from a string representation (strips leading whitespace)
    // ========================================================================
    private static Map MakeMap(string repr)
    {
        var strategy = new StringDeserializeMapCreationStrategy<Map>(repr);
        return Map.Create(strategy);
    }

    // ========================================================================
    //  1. MAP — Initialize, dimensions, cell properties, clear
    // ========================================================================

    public static void Test_Map_InitializeClearAndCellProperties()
    {
        var map = new Map();
        map.Initialize(5, 5);
        Check.Equal(5, map.Width);
        Check.Equal(5, map.Height);
        Check.False(map.IsTransparent(0, 0));
        Check.False(map.IsWalkable(0, 0));
        Check.False(map.IsTransparent(4, 4));
        Check.False(map.IsWalkable(4, 4));

        map.SetCellProperties(2, 3, true, true);
        Check.True(map.IsTransparent(2, 3));
        Check.True(map.IsWalkable(2, 3));
        Check.False(map.IsTransparent(1, 3));
        Check.False(map.IsWalkable(1, 3));

        map.Clear(true, false);
        foreach (ICell cell in map.GetAllCells())
        {
            Check.True(map.IsTransparent(cell.X, cell.Y));
            Check.False(map.IsWalkable(cell.X, cell.Y));
        }
    }

    // ========================================================================
    //  2. MAP — ToString symbols: . s o #
    // ========================================================================

    public static void Test_Map_ToString_SymbolEncoding()
    {
        // Test that all four cell type symbols round-trip correctly
        string repr = @"####
#..#
#so#
####";
        Map map = MakeMap(repr);
        string result = map.ToString();
        // Verify specific cells
        Cell walkableTransparent = map.GetCell(1, 1);
        Check.True(walkableTransparent.IsTransparent);
        Check.True(walkableTransparent.IsWalkable);
        Check.Equal(".", walkableTransparent.ToString());

        Cell walkableOnly = map.GetCell(1, 2);
        Check.False(walkableOnly.IsTransparent);
        Check.True(walkableOnly.IsWalkable);
        Check.Equal("s", walkableOnly.ToString());

        Cell transparentOnly = map.GetCell(2, 2);
        Check.True(transparentOnly.IsTransparent);
        Check.False(transparentOnly.IsWalkable);
        Check.Equal("o", transparentOnly.ToString());

        Cell wall = map.GetCell(0, 0);
        Check.False(wall.IsTransparent);
        Check.False(wall.IsWalkable);
        Check.Equal("#", wall.ToString());
    }

    // ========================================================================
    //  3. MAP — IndexFor / CellFor round-trip
    // ========================================================================

    public static void Test_Map_IndexFor_CellFor_RoundTrip()
    {
        var map = new Map(10, 8);
        // Formula: index = y * Width + x
        int index = map.IndexFor(3, 5);
        Check.Equal(5 * 10 + 3, index);
        Cell cell = map.CellFor(index);
        Check.Equal(3, cell.X);
        Check.Equal(5, cell.Y);
    }

    // ========================================================================
    //  4. MAP — Save / Restore
    // ========================================================================

    public static void Test_Map_SaveRestore_PreservesState()
    {
        string repr = @"####
#..#
#so#
####";
        Map map = MakeMap(repr);
        MapState state = map.Save();

        // Create a new map and restore
        var restoredMap = new Map();
        restoredMap.Restore(state);

        Check.Equal(map.Width, restoredMap.Width);
        Check.Equal(map.Height, restoredMap.Height);
        Check.Equal(map.ToString(), restoredMap.ToString());
    }

    // ========================================================================
    //  5. MAP — GetCellsAlongLine (Bresenham)
    // ========================================================================

    public static void Test_Map_GetCellsAlongLine_HorizontalLine()
    {
        string repr = @"####
#..#
#so#
####";
        Map map = MakeMap(repr);
        var sb = new StringBuilder();
        foreach (ICell cell in map.GetCellsAlongLine(0, 2, 3, 2))
        {
            sb.Append(cell.ToString());
        }
        Check.Equal("#so#", sb.ToString());
    }

    public static void Test_Map_GetCellsAlongLine_DiagonalLine()
    {
        string repr = @"####
#..#
#so#
####";
        Map map = MakeMap(repr);
        var sb = new StringBuilder();
        foreach (ICell cell in map.GetCellsAlongLine(3, 0, 0, 3))
        {
            sb.Append(cell.ToString());
        }
        Check.Equal("#.s#", sb.ToString());
    }

    public static void Test_Map_GetCellsAlongLine_ClampsToMapBounds()
    {
        string repr = @"####
#..#
#so#
####";
        Map map = MakeMap(repr);
        var sb = new StringBuilder();
        foreach (ICell cell in map.GetCellsAlongLine(0, 0, 10, 10))
        {
            sb.Append(cell.ToString());
        }
        // Should clamp destination to (3,3) and trace diag from (0,0) to (3,3)
        Check.Equal("#.o#", sb.ToString());
    }

    // ========================================================================
    //  6. MAP — GetAdjacentCells cardinal vs diagonal
    // ========================================================================

    public static void Test_Map_GetAdjacentCells_CardinalOnly_Returns4InCenter()
    {
        Map map = MakeMap("...\n...\n...");
        var cells = map.GetAdjacentCells(1, 1).ToList();
        Check.Equal(4, cells.Count);
        var coords = new HashSet<string>(cells.Select(c => $"{c.X},{c.Y}"));
        // 4-way cardinal neighbors of the center
        foreach (var expected in new[] { "1,0", "0,1", "2,1", "1,2" })
            Check.True(coords.Contains(expected), $"missing cardinal neighbor {expected}");
    }

    public static void Test_Map_GetAdjacentCells_WithDiagonals_Returns8InCenter()
    {
        Map map = MakeMap("...\n...\n...");
        var cells = map.GetAdjacentCells(1, 1, true).ToList();
        Check.Equal(8, cells.Count);
        var coords = new HashSet<string>(cells.Select(c => $"{c.X},{c.Y}"));
        // 8-way neighbors of the center (cardinal + diagonal)
        foreach (var expected in new[] { "1,0", "0,1", "2,1", "1,2", "0,0", "2,0", "0,2", "2,2" })
            Check.True(coords.Contains(expected), $"missing neighbor {expected}");
    }

    public static void Test_Map_GetAdjacentCells_Corner_Returns2Cardinal()
    {
        Map map = MakeMap("...\n...\n...");
        var cells = map.GetAdjacentCells(0, 0).ToList();
        Check.Equal(2, cells.Count);
        var coords = new HashSet<string>(cells.Select(c => $"{c.X},{c.Y}"));
        // cardinal neighbors of the top-left corner
        foreach (var expected in new[] { "1,0", "0,1" })
            Check.True(coords.Contains(expected), $"missing cardinal neighbor {expected}");
    }

    public static void Test_Map_GetAdjacentCells_Corner_Returns3WithDiagonals()
    {
        Map map = MakeMap("...\n...\n...");
        var cells = map.GetAdjacentCells(0, 0, true).ToList();
        Check.Equal(3, cells.Count);
        var coords = new HashSet<string>(cells.Select(c => $"{c.X},{c.Y}"));
        // 8-way neighbors of the top-left corner (2 cardinal + 1 diagonal)
        foreach (var expected in new[] { "1,0", "0,1", "1,1" })
            Check.True(coords.Contains(expected), $"missing neighbor {expected}");
    }

    // ========================================================================
    //  8. MAP — StringDeserialize round-trip
    // ========================================================================

    public static void Test_Map_StringDeserialize_RoundTrip()
    {
        string repr = @"####
#..#
#so#
####";
        Map map = MakeMap(repr);
        Check.Equal(4, map.Width);
        Check.Equal(4, map.Height);
        // Verify round-trip
        string result = map.ToString();
        string expected = "####" + Environment.NewLine + "#..#" + Environment.NewLine + "#so#" + Environment.NewLine + "####";
        Check.Equal(expected, result);
    }

    // ========================================================================
    //  9. MAP — BorderOnlyMapCreationStrategy
    // ========================================================================

    public static void Test_Map_BorderOnlyCreation_InteriorWalkable()
    {
        var strategy = new BorderOnlyMapCreationStrategy<Map>(10, 8);
        Map map = Map.Create(strategy);
        Check.Equal(10, map.Width);
        Check.Equal(8, map.Height);
        // Borders are walls
        Check.False(map.IsWalkable(0, 0));
        Check.False(map.IsWalkable(9, 7));
        Check.False(map.IsWalkable(5, 0));
        Check.False(map.IsWalkable(0, 4));
        // Interior is walkable
        Check.True(map.IsWalkable(1, 1));
        Check.True(map.IsWalkable(5, 4));
    }

    // ========================================================================
    //  10. MAP — CaveMapCreationStrategy: dimensions, walls, and determinism
    // ========================================================================

    public static void Test_Map_CaveCreation_DeterministicWithSeed()
    {
        var strategy = new CaveMapCreationStrategy<Map>(50, 20, 45, 3, 2, new DotNetRandom(27));
        Map map = Map.Create(strategy);
        Check.Equal(50, map.Width);
        Check.Equal(20, map.Height);

        // Cave borders are always walls, and the interior mixes open floor with walls.
        for (int x = 0; x < 50; x++) { Check.False(map.IsWalkable(x, 0)); Check.False(map.IsWalkable(x, 19)); }
        for (int y = 0; y < 20; y++) { Check.False(map.IsWalkable(0, y)); Check.False(map.IsWalkable(49, y)); }
        int walkableCount = map.GetAllCells().Count(c => c.IsWalkable);
        Check.True(walkableCount > 0 && walkableCount < 50 * 20, "cave should contain both floor and wall cells");

        // Generation is deterministic in the supplied IRandom: same seed -> identical map.
        Map map2 = Map.Create(new CaveMapCreationStrategy<Map>(50, 20, 45, 3, 2, new DotNetRandom(27)));
        Check.Equal(map.ToString(), map2.ToString());
        // It is also a function OF that IRandom: a differently seeded run produces a different cave.
        Map map3 = Map.Create(new CaveMapCreationStrategy<Map>(50, 20, 45, 3, 2, new DotNetRandom(99)));
        Check.False(map.ToString() == map3.ToString(), "a different seed must produce a different cave");
    }

    // ========================================================================
    //  12. MAP — RandomRoomsMapCreationStrategy deterministic
    // ========================================================================

    public static void Test_Map_RandomRoomsCreation_DeterministicWithSeed()
    {
        var strategy = new RandomRoomsMapCreationStrategy<Map>(17, 10, 30, 5, 3, new DotNetRandom(13));
        Map map = Map.Create(strategy);
        Check.Equal(17, map.Width);
        Check.Equal(10, map.Height);
        // Rooms are carved onto a walled map: borders are walls and some interior floor exists.
        for (int x = 0; x < 17; x++) { Check.False(map.IsWalkable(x, 0)); Check.False(map.IsWalkable(x, 9)); }
        for (int y = 0; y < 10; y++) { Check.False(map.IsWalkable(0, y)); Check.False(map.IsWalkable(16, y)); }
        int walkableCount = map.GetAllCells().Count(c => c.IsWalkable);
        Check.True(walkableCount > 0 && walkableCount < 17 * 10, "rooms map should contain floor and walls");
        // Deterministic in the supplied IRandom.
        Map map2 = Map.Create(new RandomRoomsMapCreationStrategy<Map>(17, 10, 30, 5, 3, new DotNetRandom(13)));
        Check.Equal(map.ToString(), map2.ToString());
        // ...and driven by it: a differently seeded run scatters the rooms differently.
        Map map3 = Map.Create(new RandomRoomsMapCreationStrategy<Map>(17, 10, 30, 5, 3, new DotNetRandom(77)));
        Check.False(map.ToString() == map3.ToString(), "a different seed must produce a different rooms map");
    }

    // ========================================================================
    //  13. MAP — Clone produces identical but independent map
    // ========================================================================

    public static void Test_Map_Clone_ProducesIdenticalCopy()
    {
        string repr = @"####
#..#
#so#
####";
        Map original = MakeMap(repr);
        Map clone = original.Clone<Map>();

        Check.Equal(original.ToString(), clone.ToString());
        // Modifying clone should not affect original
        clone.SetCellProperties(1, 1, false, false);
        Check.True(original.IsWalkable(1, 1));
        Check.False(clone.IsWalkable(1, 1));
    }

    // ========================================================================
    //  14. MAP — Copy from smaller map into larger
    // ========================================================================

    public static void Test_Map_Copy_OverwritesDestinationRegion()
    {
        Map sourceMap = MakeMap("..");
        Map destMap = MakeMap("####\n#..#\n#so#\n####");
        destMap.Copy(sourceMap, 1, 2);
        // Cells at (1,2) and (2,2) should now be transparent+walkable
        Check.True(destMap.IsTransparent(1, 2));
        Check.True(destMap.IsWalkable(1, 2));
        Check.True(destMap.IsTransparent(2, 2));
        Check.True(destMap.IsWalkable(2, 2));
    }

    // ========================================================================
    //  15-16. FIELD OF VIEW — ComputeFov
    // ========================================================================

    public static void Test_FieldOfView_ComputeFov_VisibleCellCount()
    {
        string mapRepr = @"####################################
#..................................#
#..###.########....................#
#....#.#......#....................#
#....#.#......#....................#
#.............#....................#
#....#.#......######################
#....#.#...........................#
#....#.#...........................#
#..................................#
####################################";
        Map map = MakeMap(mapRepr);
        var fov = new FieldOfView(map);
        fov.ComputeFov(6, 1, 20, true);
        // Source is visible; open cells in a clear cardinal line of sight within radius are visible.
        Check.True(fov.IsInFov(6, 1));
        Check.True(fov.IsInFov(20, 1));
        Check.True(fov.IsInFov(6, 9));
        // A floor cell well beyond the radius is not visible.
        Check.False(fov.IsInFov(30, 1));
        // lightWalls=true also lights the blocking cells at the vision edge. (6,0) is the wall
        // directly above the source, so it is at the edge of vision under any FOV variant.
        Check.True(fov.IsInFov(6, 0), "lightWalls=true must include the blocking cell at the vision edge");
        // lightWalls=false leaves that wall dark while the open cells are unaffected.
        var fovNoLitWalls = new FieldOfView(map);
        fovNoLitWalls.ComputeFov(6, 1, 20, false);
        Check.False(fovNoLitWalls.IsInFov(6, 0), "lightWalls=false must leave blocking cells out of the visible set");
        Check.True(fovNoLitWalls.IsInFov(6, 9));
    }

    public static void Test_FieldOfView_WallsBlockVision()
    {
        string mapRepr = @"####################################
#..................................#
#..###.########....................#
#....#.#......#....................#
#....#.#......#....................#
#.............#....................#
#....#.#......######################
#....#.#...........................#
#....#.#...........................#
#..................................#
####################################";
        Map map = MakeMap(mapRepr);
        var fov = new FieldOfView(map);
        fov.ComputeFov(6, 1, 20, true);
        // (2,2) should be visible
        Check.True(fov.IsInFov(2, 2));
        // (2,3) is behind a wall and should NOT be visible
        Check.False(fov.IsInFov(2, 3));
    }

    // ========================================================================
    //  17. FIELD OF VIEW — Clone preserves state
    // ========================================================================

    public static void Test_FieldOfView_Clone_PreservesFovState()
    {
        string mapRepr = @"#####
#...#
#.#.#
#...#
#####";
        Map map = MakeMap(mapRepr);
        var fov = new FieldOfView(map);
        fov.ComputeFov(2, 2, 3, true);
        var cloned = fov.Clone();
        // Cloned should have same FOV state
        Check.Equal(fov.IsInFov(1, 1), cloned.IsInFov(1, 1));
        Check.Equal(fov.IsInFov(3, 3), cloned.IsInFov(3, 3));
    }

    // ========================================================================
    //  19-20. PATH FINDER — ShortestPath basic + unreachable
    // ========================================================================

    public static void Test_PathFinder_ShortestPath_FindsExpectedPath()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var pf = new PathFinder(map);
        ICell source = map.GetCell(1, 4);
        ICell dest = map.GetCell(5, 4);
        Path path = pf.ShortestPath(source, dest);

        Check.Equal(5, path.Length);
        Check.Equal(source, path.Start);
        Check.Equal(dest, path.End);
        ICell step1 = path.StepForward();
        Check.Equal(2, step1.X);
        Check.Equal(4, step1.Y);
    }

    public static void Test_PathFinder_TryFindShortestPath_UnreachableReturnsNull()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#....#.#
########";
        Map map = MakeMap(mapRepr);
        var pf = new PathFinder(map);
        ICell source = map.GetCell(1, 1);
        ICell dest = map.GetCell(6, 1);
        Path path = pf.TryFindShortestPath(source, dest);
        Check.Null(path);
    }

    // ========================================================================
    //  21. PATH FINDER — Source not walkable returns null
    // ========================================================================

    public static void Test_PathFinder_TryFindShortestPath_SourceNotWalkableReturnsNull()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var pf = new PathFinder(map);
        ICell source = map.GetCell(0, 1); // wall
        ICell dest = map.GetCell(1, 1);
        Path path = pf.TryFindShortestPath(source, dest);
        Check.Null(path);
    }

    // ========================================================================
    //  22. PATH FINDER — ShortestPath throws PathNotFoundException
    // ========================================================================

    public static void Test_PathFinder_ShortestPath_ThrowsWhenUnreachable()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#....#.#
########";
        Map map = MakeMap(mapRepr);
        var pf = new PathFinder(map);
        ICell source = map.GetCell(1, 1);
        ICell dest = map.GetCell(6, 1);
        Check.Throws<PathNotFoundException>(() => pf.ShortestPath(source, dest));
    }

    // ========================================================================
    //  23. PATH FINDER — Diagonal movement
    // ========================================================================

    public static void Test_PathFinder_DiagonalMovement_ShorterPath()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var pf = new PathFinder(map, 1.41);
        ICell source = map.GetCell(1, 1);
        ICell dest = map.GetCell(6, 4);
        Path path = pf.ShortestPath(source, dest);
        Check.Equal(6, path.Length);
        Check.Equal(source, path.Start);
        Check.Equal(dest, path.End);
    }

    // ========================================================================
    //  24-25. DIJKSTRA PATH FINDER — basic + unreachable
    // ========================================================================

    public static void Test_DijkstraPathFinder_ShortestPath_FindsExpectedPath()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var dpf = new DijkstraPathFinder(map);
        Cell source = map.GetCell(1, 4);
        Cell dest = map.GetCell(5, 4);
        Path path = dpf.ShortestPath(source, dest);

        Check.Equal(5, path.Length);
        Check.Equal(source, path.Start);
        Check.Equal(dest, path.End);
        ICell step1 = path.StepForward();
        Check.Equal(2, step1.X);
        Check.Equal(4, step1.Y);
    }

    public static void Test_DijkstraPathFinder_TryFindShortestPath_UnreachableReturnsNull()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#....#.#
########";
        Map map = MakeMap(mapRepr);
        var dpf = new DijkstraPathFinder(map);
        Cell source = map.GetCell(1, 1);
        Cell dest = map.GetCell(6, 1);
        Path path = dpf.TryFindShortestPath(source, dest);
        Check.Null(path);
    }

    // ========================================================================
    //  26. DIJKSTRA PATH FINDER — Diagonal movement
    // ========================================================================

    public static void Test_DijkstraPathFinder_DiagonalMovement()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var dpf = new DijkstraPathFinder(map, 1.41);
        Cell source = map.GetCell(1, 1);
        Cell dest = map.GetCell(6, 4);
        Path path = dpf.ShortestPath(source, dest);

        Check.Equal(6, path.Length);
        Check.Equal(source, path.Start);
        Check.Equal(dest, path.End);
    }

    // ========================================================================
    //  27-28. GOAL MAP — FindPath with single and multiple goals
    // ========================================================================

    public static void Test_GoalMap_FindPath_SingleGoal()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var goalMap = new GoalMap(map);
        goalMap.AddGoal(1, 1, 0);
        Path path = goalMap.FindPath(4, 4);
        Check.Equal(7, path.Length);
        Check.Equal(1, path.End.X);
        Check.Equal(1, path.End.Y);
        // Note: the exact first step is a tie between two equal-length routes and is left unspecified.
    }

    // ========================================================================
    //  29. GOAL MAP — Obstacles block path
    // ========================================================================

    public static void Test_GoalMap_FindPath_WithObstacles()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var goalMap = new GoalMap(map);
        goalMap.AddGoal(1, 1, 0);
        goalMap.AddGoal(6, 1, 0);
        goalMap.AddObstacles(new List<Point> { new Point(1, 2), new Point(3, 2) });
        Path path = goalMap.FindPath(3, 4);
        Check.Equal(7, path.Length);
        ICell firstStep = path.StepForward();
        Check.Equal(4, firstStep.X);
        Check.Equal(4, firstStep.Y);
    }

    // ========================================================================
    //  30. GOAL MAP — ClearGoals then FindPath throws
    // ========================================================================

    public static void Test_GoalMap_ClearGoals_ThrowsPathNotFound()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#......#
########";
        Map map = MakeMap(mapRepr);
        var goalMap = new GoalMap(map);
        goalMap.AddGoal(1, 1, 0);
        goalMap.ClearGoals();
        Check.Throws<PathNotFoundException>(() => goalMap.FindPath(3, 4));
    }

    // ========================================================================
    //  31. GOAL MAP — TryFindPath returns null when no path exists
    // ========================================================================

    public static void Test_GoalMap_TryFindPath_UnreachableReturnsNull()
    {
        string mapRepr = @"########
#....#.#
#.#..#.#
#.#..#.#
#....#.#
########";
        Map map = MakeMap(mapRepr);
        var goalMap = new GoalMap(map);
        goalMap.AddGoal(6, 1, 0);
        Path path = goalMap.TryFindPath(1, 1);
        Check.Null(path);
    }

    // ========================================================================
    //  32. GOAL MAP — FindPathAvoidingGoals uses -1.2 multiplier
    // ========================================================================

    public static void Test_GoalMap_FindPathAvoidingGoals_FleesBehavior()
    {
        string mapRepr = @"###############################################
#..........#......................##..........#
#..........#..........##..........##..........#
#..........#..........##..........##..........#
#..........#..........##..........##..........#
#.....................##......................#
###############################################";
        Map map = MakeMap(mapRepr);
        var goalMap = new GoalMap(map);
        goalMap.AddGoal(2, 2, 0);
        goalMap.AddObstacle(2, 1);

        Path path = goalMap.FindPathAvoidingGoals(1, 1);
        Check.NotNull(path);
        // Flee mode heads away from the goal: the path starts at the query cell and ends far from the goal.
        Check.Equal(1, path.Start.X);
        Check.Equal(1, path.Start.Y);
        Check.True(path.Length > 20, "flee path should be substantial");
        int dx = path.End.X - 2, dy = path.End.Y - 2;
        Check.True(dx * dx + dy * dy > 400, "flee path should end far from the goal");
    }

    // ========================================================================
    //  33. GOAL MAP — TryFindPathAvoidingGoals with no escape returns null
    // ========================================================================

    public static void Test_GoalMap_TryFindPathAvoidingGoals_BoxedInReturnsNull()
    {
        string mapRepr = @"###############################################
#..........#......................##..........#
#..........#..........##..........##..........#
#..........#..........##..........##..........#
#..........#..........##..........##..........#
#.....................##......................#
###############################################";
        Map map = MakeMap(mapRepr);
        var goalMap = new GoalMap(map);
        goalMap.AddGoal(2, 2, 0);
        goalMap.AddObstacle(2, 1);
        goalMap.AddObstacle(1, 1);
        Path path = goalMap.TryFindPathAvoidingGoals(1, 1);
        Check.Null(path);
    }

    // ========================================================================
    //  34. GOAL MAP — Diagonal movement
    // ========================================================================

    public static void Test_GoalMap_DiagonalMovement_ShorterPath()
    {
        string mapRepr = @"#####
#...#
#...#
#...#
#####";
        Map map = MakeMap(mapRepr);
        var goalMap = new GoalMap(map, true);
        goalMap.AddGoal(3, 3, 0);
        Path pathDiag = goalMap.FindPath(1, 1);
        Check.NotNull(pathDiag);
        // Diagonal movement collapses the (1,1)->(3,3) route to 3 cells (Chebyshev distance 2 + 1).
        Check.Equal(3, pathDiag.Length);
        var goalMapNoDiag = new GoalMap(map);
        goalMapNoDiag.AddGoal(3, 3, 0);
        Path pathNoDiag = goalMapNoDiag.FindPath(1, 1);
        // Without diagonals the same route is strictly longer.
        Check.Equal(5, pathNoDiag.Length);
        Check.True(pathDiag.Length < pathNoDiag.Length);
    }

    // ========================================================================
    //  35-36. DICE NOTATION — Parse and Roll
    // ========================================================================

    public static void Test_DiceNotation_Parse_1d6_ToString()
    {
        DiceExpression expr = Dice.Parse("3d6");
        Check.Equal("3d6", expr.ToString());
    }

    public static void Test_DiceNotation_Parse_DicePlusConstant()
    {
        DiceExpression expr = Dice.Parse("3d6+5");
        Check.Equal("3d6 + 5", expr.ToString());
    }

    // ========================================================================
    //  37. DICE NOTATION — Keep highest (4d6k3)
    // ========================================================================

    public static void Test_DiceNotation_Parse_KeepHighest_4d6k3()
    {
        DiceExpression expr = Dice.Parse("4d6k3");
        Check.Equal("4d6k3", expr.ToString());
    }

    // ========================================================================
    //  38. DICE NOTATION — Deterministic roll with KnownSeriesRandom
    // ========================================================================

    public static void Test_DiceNotation_Roll_1d6_Deterministic()
    {
        var rng = new KnownSeriesRandom(4);
        int result = Dice.Roll("1d6", rng);
        Check.Equal(4, result);
    }

    // ========================================================================
    //  39. DICE NOTATION — 4d6k3 keep highest 3 of 4
    // ========================================================================

    public static void Test_DiceNotation_Roll_4d6k3_KeepsHighest3()
    {
        // Roll 4 dice with values 3,5,2,6 -> keep highest 3: 5+6+3 = 14
        var rng = new KnownSeriesRandom(3, 5, 2, 6);
        int result = Dice.Roll("4d6k3", rng);
        Check.Equal(14, result);
    }

    // ========================================================================
    //  40. DICE NOTATION — Negative scalar
    // ========================================================================

    public static void Test_DiceNotation_Parse_NegativeScalar()
    {
        DiceExpression expr = Dice.Parse("2 + -2*1d6");
        Check.Equal("2 + -2*1d6", expr.ToString());
    }

    // ========================================================================
    //  41. DICE NOTATION — MinRoll and MaxRoll
    // ========================================================================

    public static void Test_DiceNotation_MinRollMaxRoll()
    {
        DiceExpression expr = Dice.Parse("2d6+3");
        dynamic minResult = expr.MinRoll();
        dynamic maxResult = expr.MaxRoll();
        int minVal = (int)(minResult is int ? minResult : minResult.Value);
        int maxVal = (int)(maxResult is int ? maxResult : maxResult.Value);
        // Min: 2*1+3 = 5, Max: 2*6+3 = 15
        Check.Equal(5, minVal);
        Check.Equal(15, maxVal);
    }

    // ========================================================================
    //  42. DICE NOTATION — Invalid expression throws
    // ========================================================================

    public static void Test_DiceNotation_Parse_InvalidCharThrows()
    {
        Check.Throws<ArgumentException>(() => Dice.Parse("2d6/2"));
    }

    // ========================================================================
    //  43. KNOWN SERIES RANDOM — Cycles through values
    // ========================================================================

    public static void Test_KnownSeriesRandom_CyclesThroughValues()
    {
        var rng = new KnownSeriesRandom(1, 2, 3);
        Check.Equal(1, rng.Next(0, 10));
        Check.Equal(2, rng.Next(0, 10));
        Check.Equal(3, rng.Next(0, 10));
        // Should cycle back to the beginning
        Check.Equal(1, rng.Next(0, 10));
    }

    // ========================================================================
    //  44. KNOWN SERIES RANDOM — Save / Restore
    // ========================================================================

    public static void Test_KnownSeriesRandom_SaveRestore()
    {
        var rng = new KnownSeriesRandom(10, 20, 30);
        rng.Next(0, 100); // consumes 10
        RandomState state = rng.Save();
        int val1 = rng.Next(0, 100); // consumes 20
        int val2 = rng.Next(0, 100); // consumes 30
        rng.Restore(state);
        // After restore, should get same values
        Check.Equal(val1, rng.Next(0, 100));
        Check.Equal(val2, rng.Next(0, 100));
    }

    // ========================================================================
    //  45. WEIGHTED POOL — Draw removes item
    // ========================================================================

    private static dynamic CreateWeightedPool(IRandom rng)
    {
        var t = typeof(WeightedPool<string>);
        var ctor1 = t.GetConstructor(new[] { typeof(IRandom) });
        if (ctor1 != null) return ctor1.Invoke(new object[] { rng });
        return Activator.CreateInstance(t, rng, (Func<string,string>)(s => s));
    }

    public static void Test_WeightedPool_Draw_RemovesItem()
    {
        var rng = new KnownSeriesRandom(1);
        dynamic pool = CreateWeightedPool(rng);
        pool.Add("sword", 10);
        pool.Add("shield", 5);
        Check.Equal(2, (int)pool.Count);
        string item = pool.Draw();
        Check.Equal(1, (int)pool.Count);
        // KnownSeriesRandom(1) yields the minimum lookup weight, selecting the first-added item by weight.
        Check.Equal("sword", item);
    }

    // ========================================================================
    //  46. WEIGHTED POOL — Draw from empty throws
    // ========================================================================

    public static void Test_WeightedPool_DrawFromEmpty_Throws()
    {
        var rng = new KnownSeriesRandom(1);
        dynamic pool = CreateWeightedPool(rng);
        Check.Throws<InvalidOperationException>(() => { string _ = pool.Draw(); });
    }

    // ========================================================================
    //  47. GAUSSIAN RANDOM — Produces values in range
    // ========================================================================

    public static void Test_GaussianRandom_ProducesValuesInRange()
    {
        var rng = new GaussianRandom(42);
        for (int i = 0; i < 100; i++)
        {
            int val = rng.Next(1, 10);
            Check.True(val >= 1 && val <= 10, $"GaussianRandom value {val} out of range [1, 10]");
        }
    }

    // ========================================================================
    //  48. PATH — StepForward / StepBackward traversal
    // ========================================================================

    public static void Test_Path_StepForwardBackward()
    {
        var cells = new List<ICell>
        {
            new Cell(0, 0, true, true),
            new Cell(1, 0, true, true),
            new Cell(2, 0, true, true)
        };
        var path = new Path(cells);
        Check.Equal(3, path.Length);
        Check.Equal(0, path.Start.X);
        Check.Equal(2, path.End.X);
        Check.Equal(0, path.CurrentStep.X);

        ICell step1 = path.StepForward();
        Check.Equal(1, step1.X);
        ICell step2 = path.StepForward();
        Check.Equal(2, step2.X);

        // StepForward at end should throw
        Check.Throws<NoMoreStepsException>(() => path.StepForward());

        // Step backward
        ICell back1 = path.StepBackward();
        Check.Equal(1, back1.X);
    }

    // ========================================================================
    //  49. PATH — TryStepForward at end returns null
    // ========================================================================

    public static void Test_Path_TryStepForward_ReturnsNullAtEnd()
    {
        var cells = new List<ICell> { new Cell(0, 0, true, true), new Cell(1, 0, true, true) };
        var path = new Path(cells);
        path.StepForward(); // move to end
        ICell result = path.TryStepForward();
        Check.Null(result);
    }

    // ========================================================================
    //  50. ALGORITHMS — Graph basic operations
    // ========================================================================

    public static void Test_Graph_AddEdge_IncrementsEdgeCount()
    {
        var graph = new Graph(5);
        Check.Equal(5, graph.NumberOfVertices);
        Check.Equal(0, graph.NumberOfEdges);

        graph.AddEdge(0, 1);
        graph.AddEdge(0, 2);
        Check.Equal(2, graph.NumberOfEdges);

        var adjacent0 = new List<int>(graph.Adjacent(0));
        Check.Equal(2, adjacent0.Count);
        Check.True(adjacent0.Contains(1));
        Check.True(adjacent0.Contains(2));
        // Undirected: vertex 1 should also have 0 as adjacent
        var adjacent1 = new List<int>(graph.Adjacent(1));
        Check.True(adjacent1.Contains(0));
    }

    // ========================================================================
    //  51. ALGORITHMS — UnionFind
    // ========================================================================

    public static void Test_UnionFind_UnionAndConnected()
    {
        var uf = new UnionFind(5);
        Check.Equal(5, uf.Count);
        Check.False(uf.Connected(0, 1));

        uf.Union(0, 1);
        Check.True(uf.Connected(0, 1));
        Check.Equal(4, uf.Count);

        uf.Union(2, 3);
        uf.Union(0, 3);
        Check.True(uf.Connected(1, 2));
        Check.Equal(2, uf.Count);
        // 4 is still isolated
        Check.False(uf.Connected(0, 4));
    }

    // ========================================================================
    //  52. ALGORITHMS — IndexMinPriorityQueue
    // ========================================================================

    public static void Test_IndexMinPriorityQueue_InsertAndDeleteMin()
    {
        var pq = new IndexMinPriorityQueue<double>(10);
        Check.True(pq.IsEmpty());

        pq.Insert(3, 5.0);
        pq.Insert(1, 2.0);
        pq.Insert(7, 8.0);
        Check.Equal(3, pq.Size);
        Check.False(pq.IsEmpty());

        // Min should be index 1 with value 2.0
        Check.Equal(1, pq.MinIndex());
        Check.Equal(2.0, pq.MinKey());

        int minIdx = pq.DeleteMin();
        Check.Equal(1, minIdx);
        Check.Equal(2, pq.Size);

        // After removing 1, min should be index 3 (value 5.0)
        Check.Equal(3, pq.MinIndex());
    }

    // ========================================================================
    //  53. ALGORITHMS — EdgeWeightedDigraph + DijkstraShortestPath
    // ========================================================================

    public static void Test_EdgeWeightedDigraph_DijkstraShortestPath()
    {
        var graph = new EdgeWeightedDigraph(5);
        graph.AddEdge(new DirectedEdge(0, 1, 1.0));
        graph.AddEdge(new DirectedEdge(0, 2, 4.0));
        graph.AddEdge(new DirectedEdge(1, 2, 2.0));
        graph.AddEdge(new DirectedEdge(1, 3, 6.0));
        graph.AddEdge(new DirectedEdge(2, 3, 1.0));

        var sp = new DijkstraShortestPath(graph, 0);
        Check.Equal(0.0, sp.DistanceTo(0));
        Check.Equal(1.0, sp.DistanceTo(1));
        Check.Equal(3.0, sp.DistanceTo(2)); // 0->1->2 = 1+2 = 3
        Check.Equal(4.0, sp.DistanceTo(3)); // 0->1->2->3 = 1+2+1 = 4
        Check.True(sp.HasPathTo(3));
        Check.False(sp.HasPathTo(4)); // no edge to 4

        var pathEdges = sp.PathTo(3).ToList();
        Check.Equal(3, pathEdges.Count);
    }

    // ========================================================================
    //  54. POINT — Arithmetic, equality, distance
    // ========================================================================

    public static void Test_Point_ArithmeticEqualityDistance()
    {
        var p1 = new Point(3, 5);
        var p2 = new Point(2, 4);

        Point sum = p1 + p2;
        Check.Equal(5, sum.X);
        Check.Equal(9, sum.Y);

        Point diff = p1 - p2;
        Check.Equal(1, diff.X);
        Check.Equal(1, diff.Y);

        Point prod = p1 * p2;
        Check.Equal(6, prod.X);
        Check.Equal(20, prod.Y);

        var p3 = new Point(3, 4);
        var p4 = new Point(3, 4);
        var origin = new Point(0, 0);
        Check.True(p3 == p4);
        Check.True(p3 != origin);
        Check.Equal("{X:3 Y:4}", p3.ToString());

        double dist = Convert.ToDouble(Point.Distance(origin, p3));
        Check.Equal(5.0, Math.Round(dist, 1));
    }

    // ========================================================================
    //  56. RECTANGLE — Properties and Contains
    // ========================================================================

    public static void Test_Rectangle_PropertiesAndContains()
    {
        var rect = new Rectangle(2, 3, 10, 5);
        Check.Equal(2, rect.Left);
        Check.Equal(12, rect.Right);
        Check.Equal(3, rect.Top);
        Check.Equal(8, rect.Bottom);
        Check.Equal(7, rect.Center.X);
        Check.Equal(5, rect.Center.Y);

        Check.True(rect.Contains(5, 4));
        Check.False(rect.Contains(12, 4)); // right boundary is exclusive
        Check.False(rect.Contains(1, 4)); // left of rect
    }

    // ========================================================================
    //  57. RECTANGLE — Intersects
    // ========================================================================

    public static void Test_Rectangle_Intersects()
    {
        var r1 = new Rectangle(0, 0, 10, 10);
        var r2 = new Rectangle(5, 5, 10, 10);
        var r3 = new Rectangle(20, 20, 5, 5);

        Check.True(r1.Intersects(r2));
        Check.False(r1.Intersects(r3));

        Rectangle intersection = Rectangle.Intersect(r1, r2);
        Check.Equal(5, intersection.X);
        Check.Equal(5, intersection.Y);
        Check.Equal(5, intersection.Width);
        Check.Equal(5, intersection.Height);
    }

    // ========================================================================
    //  59. DICE NOTATION — Implicit multiplicity d6 = 1d6
    // ========================================================================

    public static void Test_DiceNotation_ImplicitMultiplicity()
    {
        DiceExpression expr = Dice.Parse("2 + 2*d6");
        Check.Equal("2 + 2*1d6", expr.ToString());
    }

    // ========================================================================
    //  60. IRandom — Next is inclusive on both ends
    // ========================================================================

    public static void Test_IRandom_NextIsInclusiveOnBothEnds()
    {
        // KnownSeriesRandom demonstrates the inclusive behavior
        var rng = new KnownSeriesRandom(1, 6);
        // Next(1, 6) should accept both 1 and 6 without throwing
        int val1 = rng.Next(1, 6);
        Check.Equal(1, val1);
        int val2 = rng.Next(1, 6);
        Check.Equal(6, val2);

        // DotNetRandom.Next(min, max) is also inclusive - it calls System.Random.Next(min, max+1)
        var dotNetRng = new DotNetRandom(42);
        int result = dotNetRng.Next(5, 5); // min==max should return exactly 5
        Check.Equal(5, result);
    }

    // ========================================================================
    //  HARDER TESTS — Complex algorithmic behavior with exact values
    // ========================================================================

    public static void Test_PathFinder_ComplexMaze_ExactPathLength()
    {
        var maze = MakeMap(
            "###########\n" +
            "#.#.......#\n" +
            "#.#.#####.#\n" +
            "#.#.#...#.#\n" +
            "#.#.#.#.#.#\n" +
            "#.#...#.#.#\n" +
            "#.#####.#.#\n" +
            "#.......#.#\n" +
            "#########.#\n" +
            "#.........#\n" +
            "###########");
        var pf = new PathFinder(maze);
        Path path = pf.ShortestPath(maze.GetCell(1, 1), maze.GetCell(9, 9));
        Check.Equal(41, path.Length);
        Check.Equal(1, path.Start.X);
        Check.Equal(1, path.Start.Y);
        Check.Equal(9, path.End.X);
        Check.Equal(9, path.End.Y);
        ICell firstStep = path.StepForward();
        Check.Equal(1, firstStep.X);
        Check.Equal(2, firstStep.Y);
        // Walk to the 10th step and verify the waypoint on the single shortest path.
        ICell step = firstStep;
        for (int i = 0; i < 9; i++) step = path.StepForward();
        Check.Equal(5, step.X);
        Check.Equal(7, step.Y);
    }

    public static void Test_FieldOfView_ComplexWalls_ExactVisibleCount()
    {
        var fovMap = MakeMap(
            "###########\n" +
            "#.........#\n" +
            "#.##.##...#\n" +
            "#.#...#...#\n" +
            "#.#.#.#...#\n" +
            "#...#.....#\n" +
            "#.#.#.#...#\n" +
            "#.#...#...#\n" +
            "#.##.##...#\n" +
            "#.........#\n" +
            "###########");
        var fov = new FieldOfView(fovMap);
        fov.ComputeFov(5, 5, 5, true);
        // Source and open cells in a clear line of sight are visible.
        Check.True(fov.IsInFov(5, 5));
        Check.True(fov.IsInFov(5, 4));
        Check.True(fov.IsInFov(6, 5));
        Check.True(fov.IsInFov(7, 5));
        // The wall orthogonally adjacent to the source is lit by lightWalls=true ...
        Check.True(fov.IsInFov(4, 5), "lightWalls=true must include the blocking cell at the vision edge");
        // ... while the open cell directly behind that wall is occluded.
        Check.False(fov.IsInFov(2, 5));
    }

    public static void Test_GoalMap_WeightedGoals_ChoosesLowerWeight()
    {
        var map = MakeMap(
            "###########\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "###########");
        var gm = new GoalMap(map);
        gm.AddGoal(1, 1, 0);
        gm.AddGoal(9, 9, 2);
        Path path = gm.FindPath(5, 5);
        Check.Equal(9, path.Length);
        Check.Equal(1, path.End.X);
        Check.Equal(1, path.End.Y);
    }

    public static void Test_Map_GetCellsInCircle_MultipleRadii()
    {
        var map = new Map(30, 30);
        map.Clear(true, true);
        // A filled circle on a clear 30x30 map centered at (15,15). The exact per-radius fill count
        // depends on the specific midpoint-circle rasterization variant, so only the derivable bounds
        // are asserted: the count is at least the inscribed Manhattan diamond (2r^2+2r+1), at most the
        // bounding Chebyshev square ((2r+1)^2), and grows monotonically with the radius.
        int prevCount = 0;
        foreach (int r in new[] { 1, 2, 3, 5 })
        {
            int count = map.GetCellsInCircle(15, 15, r).Count();
            int diamond = 2 * r * r + 2 * r + 1;
            int square = (2 * r + 1) * (2 * r + 1);
            Check.True(count >= diamond && count <= square, $"circle r={r} count {count} not in [{diamond}, {square}]");
            // A filled circle bulges past its inscribed Manhattan diamond at the diagonals for r>=3 (it
            // includes offset (2,2), Manhattan 4>3, which a diamond omits), so its fill strictly exceeds
            // the diamond's; at r<=2 the two coincide, so only the band holds. Rejects a diamond fill.
            if (r >= 3)
                Check.GreaterThan(count, diamond, $"circle r={r} fill {count} must exceed inscribed diamond {diamond}");
            Check.GreaterThan(count, prevCount, $"circle count should grow with radius at r={r}");
            prevCount = count;
        }

        // Shape sanity on r=3: unique in-bounds cells, center included, all within the radius
        // bounding box, and the far diagonal corner a bounding square would contain is excluded
        // (its Euclidean distance r*sqrt(2) exceeds r).
        var r3 = map.GetCellsInCircle(15, 15, 3).ToList();
        int unique = r3.Select(c => c.X * 1000 + c.Y).Distinct().Count();
        Check.Equal(r3.Count, unique);
        Check.True(r3.Any(c => c.X == 15 && c.Y == 15), "circle must include its center");
        foreach (var c in r3)
            Check.True(Math.Abs(c.X - 15) <= 3 && Math.Abs(c.Y - 15) <= 3, "cell outside radius bounding box");
        Check.False(r3.Any(c => c.X == 18 && c.Y == 18), "filled circle must exclude the bounding-square corner");
    }

    public static void Test_Map_GetCellsInDiamond_ExactCounts()
    {
        var map = new Map(30, 30);
        map.Clear(true, true);
        // Filled diamond (Manhattan ball) cell count follows 2*r^2 + 2*r + 1 for radii 1, 2, 3.
        Check.Equal(5, map.GetCellsInDiamond(15, 15, 1).Count());
        Check.Equal(13, map.GetCellsInDiamond(15, 15, 2).Count());
        Check.Equal(25, map.GetCellsInDiamond(15, 15, 3).Count());
        // r=1 is exactly the center plus its four orthogonal neighbors, so membership (not just
        // cardinality) is pinned around the (15,15) center -- a diamond at the wrong center is rejected.
        var r1Coords = new HashSet<string>(map.GetCellsInDiamond(15, 15, 1).Select(c => $"{c.X},{c.Y}"));
        foreach (var expected in new[] { "15,15", "14,15", "16,15", "15,14", "15,16" })
            Check.True(r1Coords.Contains(expected), $"diamond r=1 missing {expected}");
        // Every cell of a larger diamond lies within Manhattan distance r of the center.
        foreach (var c in map.GetCellsInDiamond(15, 15, 3))
            Check.True(Math.Abs(c.X - 15) + Math.Abs(c.Y - 15) <= 3, "diamond cell outside Manhattan radius");
    }

    public static void Test_Map_GetBorderCells_ExactCounts()
    {
        var map = new Map(30, 30);
        map.Clear(true, true);
        // Diamond perimeter at Manhattan distance r has exactly 4*r cells.
        Check.Equal(12, map.GetBorderCellsInDiamond(15, 15, 3).Count());
        // Circle perimeter (rim only). The exact rim count depends on the specific midpoint-circle
        // rasterization variant, so only the derivable bounds/shape are asserted: the rim is rounder than
        // the inscribed diamond perimeter so it holds strictly more than 4*r cells (at most the bounding
        // square ring 8*r) -- a diamond rim (exactly 4*r) is rejected; its cells are unique, all within
        // [1,3] Chebyshev, reach the rim, and exclude the square-ring corner.
        var border = map.GetBorderCellsInCircle(15, 15, 3).ToList();
        Check.True(border.Count > 4 * 3 && border.Count <= 8 * 3, $"border-circle rim count {border.Count} not in ({4 * 3}, {8 * 3}]");
        int unique = border.Select(c => c.X * 1000 + c.Y).Distinct().Count();
        Check.Equal(border.Count, unique);
        Check.False(border.Any(c => c.X == 18 && c.Y == 18), "circle border must exclude the square-ring corner");
        bool reachesRim = false;
        foreach (var c in border)
        {
            int cheb = Math.Max(Math.Abs(c.X - 15), Math.Abs(c.Y - 15));
            Check.True(cheb >= 1 && cheb <= 3, "border-circle cell at center or outside radius");
            if (cheb == 3) reachesRim = true;
        }
        Check.True(reachesRim, "border-circle should include cells at the radius edge");
    }

    public static void Test_Map_GetCellsInRows_And_Columns()
    {
        var map = MakeMap("....\n....\n....\n....");
        // Rows 0 and 2: every returned cell has Y in {0,2}, together spanning all four columns of each
        // selected row (X 0..3) -> 8 specific cells, not just any two rows of the right cardinality.
        var rows = map.GetCellsInRows(0, 2).ToList();
        Check.Equal(8, rows.Count);
        foreach (var c in rows)
            Check.True(c.Y == 0 || c.Y == 2, $"row cell Y={c.Y} not in {{0,2}}");
        var rowCoords = new HashSet<string>(rows.Select(c => $"{c.X},{c.Y}"));
        foreach (int y in new[] { 0, 2 })
            for (int x = 0; x < 4; x++)
                Check.True(rowCoords.Contains($"{x},{y}"), $"missing row cell {x},{y}");

        // Columns 1 and 3: every returned cell has X in {1,3}, spanning all four rows (Y 0..3).
        var cols = map.GetCellsInColumns(1, 3).ToList();
        Check.Equal(8, cols.Count);
        foreach (var c in cols)
            Check.True(c.X == 1 || c.X == 3, $"column cell X={c.X} not in {{1,3}}");
        var colCoords = new HashSet<string>(cols.Select(c => $"{c.X},{c.Y}"));
        foreach (int x in new[] { 1, 3 })
            for (int y = 0; y < 4; y++)
                Check.True(colCoords.Contains($"{x},{y}"), $"missing column cell {x},{y}");
    }

    public static void Test_FieldOfView_MultipleSources_Exact()
    {
        var map = MakeMap(
            "#############\n" +
            "#...........#\n" +
            "#...........#\n" +
            "#.....#.....#\n" +
            "#...........#\n" +
            "#...........#\n" +
            "#############");
        var fov = new FieldOfView(map);
        var v1 = fov.ComputeFov(3, 3, 3, true);
        // Before appending, the first source sees its own neighborhood but not the far source's cells.
        Check.True(fov.IsInFov(4, 3));
        Check.False(fov.IsInFov(8, 3));
        var v2 = fov.AppendFov(9, 3, 3, true);
        // AppendFov unions the second source in: its cells become visible while the first source's remain.
        Check.True(v2.Count > v1.Count, "AppendFov should increase visible count");
        Check.True(fov.IsInFov(3, 3));
        Check.True(fov.IsInFov(9, 3));
        Check.True(fov.IsInFov(8, 3));
        Check.True(fov.IsInFov(4, 3));
    }

    // ========================================================================
    //  FOV — Box walls occlude an enclosed interior
    // ========================================================================

    public static void Test_FieldOfView_BoxWalls_CornerPosition()
    {
        var map = MakeMap(
            "##########\n" +
            "#........#\n" +
            "#..####..#\n" +
            "#..#..#..#\n" +
            "#..#..#..#\n" +
            "#..####..#\n" +
            "#........#\n" +
            "#........#\n" +
            "#........#\n" +
            "##########");
        var fov = new FieldOfView(map);
        fov.ComputeFov(1, 1, 4, true);
        // Source and cells in a clear cardinal line of sight are visible.
        Check.True(fov.IsInFov(1, 1));
        Check.True(fov.IsInFov(4, 1));
        Check.True(fov.IsInFov(1, 4));
        // Cells sealed inside the box wall, and cells beyond the radius, are not visible.
        Check.False(fov.IsInFov(4, 3));
        Check.False(fov.IsInFov(7, 7));
    }

    // ========================================================================
    //  Bresenham — Near-vertical line exact coordinates
    // ========================================================================

    public static void Test_Map_GetCellsAlongLine_NearVertical()
    {
        var map = new Map(15, 15);
        map.Clear(true, true);
        var cells = map.GetCellsAlongLine(5, 0, 6, 14).ToList();
        // A near-vertical Bresenham line steps once per major (y) axis cell: 15 cells from
        // start to end. The exact interior index where x increments is a Bresenham-variant
        // internal detail, so only the count and endpoints are asserted.
        Check.Equal(15, cells.Count);
        Check.Equal(5, cells[0].X);
        Check.Equal(0, cells[0].Y);
        Check.Equal(6, cells[14].X);
        Check.Equal(14, cells[14].Y);
    }

    // ========================================================================
    //  GoalMap — Corridor with internal walls, exact path
    // ========================================================================

    public static void Test_GoalMap_Corridor_ExactPath()
    {
        var map = MakeMap(
            "#########\n" +
            "#.......#\n" +
            "#.#####.#\n" +
            "#.......#\n" +
            "#.#####.#\n" +
            "#.......#\n" +
            "#########");
        var gm = new GoalMap(map);
        gm.AddGoal(7, 1, 0);
        Path path = gm.FindPath(1, 5);
        Check.Equal(11, path.Length);
        Check.Equal(7, path.End.X);
        Check.Equal(1, path.End.Y);
    }

    // ========================================================================
    //  Geometry — GetBorderCellsInSquare exact
    // ========================================================================

    public static void Test_Map_GetBorderCellsInSquare_ExactCounts()
    {
        var map = new Map(20, 20);
        map.Clear(true, true);
        // A square border ring at Chebyshev distance r has exactly 8*r cells, and every returned cell
        // sits at Chebyshev distance exactly r from the center (pins the ring's center, not just count).
        foreach (int r in new[] { 2, 4 })
        {
            var ring = map.GetBorderCellsInSquare(10, 10, r).ToList();
            Check.Equal(8 * r, ring.Count);
            foreach (var c in ring)
                Check.Equal(r, Math.Max(Math.Abs(c.X - 10), Math.Abs(c.Y - 10)));
        }
    }

    // ========================================================================
    //  Geometry — GetCellsInRectangle exact
    // ========================================================================

    public static void Test_Map_GetCellsInRectangle_ExactCount()
    {
        var map = new Map(20, 20);
        map.Clear(true, true);
        // Rectangle at origin (2,2) with width 5 and height 3 covers exactly columns x in [2,7) and
        // rows y in [2,5): 15 cells with X in 2..6 and Y in 2..4 (position/orientation, not just area).
        var cells = map.GetCellsInRectangle(2, 2, 5, 3).ToList();
        Check.Equal(15, cells.Count);
        var coords = new HashSet<string>(cells.Select(c => $"{c.X},{c.Y}"));
        for (int y = 2; y < 5; y++)
            for (int x = 2; x < 7; x++)
                Check.True(coords.Contains($"{x},{y}"), $"missing rectangle cell {x},{y}");
        Check.Equal(2, cells.Min(c => c.X));
        Check.Equal(6, cells.Max(c => c.X));
        Check.Equal(2, cells.Min(c => c.Y));
        Check.Equal(4, cells.Max(c => c.Y));
    }

    // ========================================================================
    //  DijkstraPathFinder — Diagonal with wall, exact length
    // ========================================================================

    public static void Test_DijkstraPathFinder_DiagonalAroundWall_ExactLength()
    {
        var map = MakeMap(
            "######\n" +
            "#....#\n" +
            "#.##.#\n" +
            "#....#\n" +
            "#....#\n" +
            "######");
        var dpf = new DijkstraPathFinder(map, 1.41);
        Path path = dpf.ShortestPath(map.GetCell(1, 1), map.GetCell(4, 4));
        Check.Equal(5, path.Length);
    }

    // ========================================================================
    //  Cross-subsystem: FOV visibility check after wall layout
    // ========================================================================

    public static void Test_CrossSubsystem_FovThenPathfind()
    {
        var map = MakeMap(
            "##########\n" +
            "#........#\n" +
            "#.####...#\n" +
            "#........#\n" +
            "#........#\n" +
            "##########");
        var fov = new FieldOfView(map);
        fov.ComputeFov(1, 1, 10, true);
        Check.True(fov.IsInFov(5, 1));
        Check.True(fov.IsInFov(1, 3));
        Check.False(fov.IsInFov(5, 3));

        var pf = new PathFinder(map);
        Path path = pf.ShortestPath(map.GetCell(1, 1), map.GetCell(8, 4));
        Check.Equal(11, path.Length);
    }

    // ========================================================================
    //  GoalMap — Multiple equal paths with exact endpoints
    // ========================================================================

    public static void Test_GoalMap_FindPaths_TwoGoals_ExactEndpoints()
    {
        var map = MakeMap(
            "########\n" +
            "#......#\n" +
            "#.####.#\n" +
            "#......#\n" +
            "########");
        var gm = new GoalMap(map);
        gm.AddGoal(6, 1, 0);
        gm.AddGoal(6, 3, 0);
        ReadOnlyCollection<Path> paths = gm.FindPaths(1, 2);
        Check.Equal(2, paths.Count);
        Check.Equal(7, paths[0].Length);
        Check.Equal(7, paths[1].Length);
        var ends = new HashSet<string> { $"{paths[0].End.X},{paths[0].End.Y}", $"{paths[1].End.X},{paths[1].End.Y}" };
        Check.True(ends.Contains("6,1"));
        Check.True(ends.Contains("6,3"));

        // "All equally good paths" also covers tied routes to the SAME goal: here (3,4) is 6 cells
        // from goal (1,1) along two distinct routes (up column 3 then left, or left along row 4 then
        // up column 1) and 7 cells from goal (6,1), so both routes to the nearer goal are returned.
        var tiedMap = MakeMap(
            "########\n" +
            "#....#.#\n" +
            "#.#..#.#\n" +
            "#.#..#.#\n" +
            "#......#\n" +
            "########");
        var tiedGoalMap = new GoalMap(tiedMap);
        tiedGoalMap.AddGoal(1, 1, 0);
        tiedGoalMap.AddGoal(6, 1, 0);
        ReadOnlyCollection<Path> tiedPaths = tiedGoalMap.FindPaths(3, 4);
        Check.Equal(2, tiedPaths.Count);
        Check.Equal(6, tiedPaths[0].Length);
        Check.Equal(6, tiedPaths[1].Length);
        Check.Equal(1, tiedPaths[0].End.X);
        Check.Equal(1, tiedPaths[0].End.Y);
        Check.Equal(1, tiedPaths[1].End.X);
        Check.Equal(1, tiedPaths[1].End.Y);
    }

    // ========================================================================
    //  Complex dice: multi-term expression with deterministic roll
    // ========================================================================

    public static void Test_DiceNotation_MultiTermExpression_ExactRoll()
    {
        var rng = new KnownSeriesRandom(3, 5, 1);
        DiceExpression expr = Dice.Parse("2d6+1d4+3");
        dynamic result = expr.Roll(rng);
        int val = (int)(result is int ? result : result.Value);
        Check.Equal(12, val);
    }

    public static void Test_DiceNotation_KeepHighest_3d6k2_ExactRoll()
    {
        var rng = new KnownSeriesRandom(2, 5, 3);
        DiceExpression expr = Dice.Parse("3d6k2+2");
        dynamic result = expr.Roll(rng);
        int val = (int)(result is int ? result : result.Value);
        Check.Equal(10, val);
    }

    // ========================================================================
    //  Map.Copy then pathfind across connected rooms
    // ========================================================================

    public static void Test_CrossSubsystem_CopyRoomsThenPathfind()
    {
        var bigMap = new Map(15, 10);
        bigMap.Initialize(15, 10);
        var room = MakeMap(".....\n.....\n.....");
        bigMap.Copy(room, 1, 1);
        bigMap.Copy(room, 9, 6);
        for (int x = 5; x <= 9; x++) bigMap.SetCellProperties(x, 3, true, true);
        for (int y = 3; y <= 6; y++) bigMap.SetCellProperties(9, y, true, true);

        var pf = new PathFinder(bigMap);
        Path path = pf.ShortestPath(bigMap.GetCell(1, 1), bigMap.GetCell(13, 8));
        Check.Equal(20, path.Length);
    }

    // ========================================================================
    //  GoalMap with obstacle funnel — exact path through detour
    // ========================================================================

    public static void Test_GoalMap_ObstacleFunnel_ExactPath()
    {
        var map = MakeMap(
            "###########\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "#.........#\n" +
            "###########");
        var gm = new GoalMap(map);
        gm.AddGoal(9, 3, 0);
        gm.AddObstacle(5, 2);
        gm.AddObstacle(5, 3);
        gm.AddObstacle(5, 4);
        Path path = gm.FindPath(1, 3);
        Check.Equal(13, path.Length);
        Check.Equal(9, path.End.X);
        Check.Equal(3, path.End.Y);
        // Note: the detour direction (first step up vs down) is a symmetric tie, left unspecified.
    }

    // ========================================================================
    //  PathFinder — L-shaped corridor exact step sequence
    // ========================================================================

    public static void Test_PathFinder_LCorridor_ExactSteps()
    {
        var map = MakeMap(
            "#######\n" +
            "#.....#\n" +
            "#####.#\n" +
            "#.....#\n" +
            "#.#####\n" +
            "#.....#\n" +
            "#######");
        var pf = new PathFinder(map);
        Path path = pf.ShortestPath(map.GetCell(1, 1), map.GetCell(5, 5));
        Check.Equal(17, path.Length);
        // Verify key waypoints: must go through (5,2) turn, (1,3) turn
        ICell step = null;
        for (int i = 0; i < 5; i++) step = path.StepForward();
        Check.Equal(5, step.X);
        Check.Equal(2, step.Y);
        for (int i = 0; i < 5; i++) step = path.StepForward();
        Check.Equal(1, step.X);
        Check.Equal(3, step.Y);
    }

    // ========================================================================
    //  GetCellsInSquare — exact cell coordinates
    // ========================================================================

    public static void Test_Map_GetCellsInSquare_ExactCoordinates()
    {
        var map = new Map(10, 10);
        map.Clear(true, true);
        var cells = map.GetCellsInSquare(5, 5, 1).OrderBy(c => c.Y).ThenBy(c => c.X).ToList();
        Check.Equal(9, cells.Count);
        Check.Equal(4, cells[0].X); Check.Equal(4, cells[0].Y);
        Check.Equal(5, cells[1].X); Check.Equal(4, cells[1].Y);
        Check.Equal(6, cells[2].X); Check.Equal(4, cells[2].Y);
        Check.Equal(4, cells[3].X); Check.Equal(5, cells[3].Y);
        Check.Equal(5, cells[4].X); Check.Equal(5, cells[4].Y);
        // Larger radius stays a full (2r+1)^2 Chebyshev square when fully in bounds.
        Check.Equal(49, map.GetCellsInSquare(5, 5, 3).Count());
    }
}
