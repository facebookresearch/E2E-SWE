"""Hidden test suite for the b3d WRG task.

Each test builds a small C driver against the installed libb3d
(`#include <b3d*.h>`, `-lb3d -lm`) and asserts on the driver's
stdout / return code. Rendering tests use pixel-count and center-pixel
checks — never pixel-exact frame comparisons — to stay tolerant of
fixed-point interpolation rounding while still catching wholesale-broken
implementations.
"""

# ---------------------------------------------------------------------------
# Init + framebuffer
# ---------------------------------------------------------------------------


def test_init_and_state_queries(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*48];
        static b3d_depth_t dp[64*48];
        printf("pre=%d\n", (int)b3d_is_initialized());
        int ok = b3d_init(px, dp, 64, 48, 75.0f);
        printf("init=%d post=%d w=%d h=%d fov=%.1f\n",
               ok, (int)b3d_is_initialized(),
               b3d_get_width(), b3d_get_height(),
               (double)b3d_get_fov());
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "init=1 post=1 w=64 h=48 fov=75.0" in r.stdout


def test_init_rejects_invalid_and_buffer_size(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        int a = b3d_init(NULL, dp, 16, 16, 60.0f);
        int b = b3d_init(px, NULL, 16, 16, 60.0f);
        int c = b3d_init(px, dp,  0, 16, 60.0f);
        int d = b3d_init(px, dp, 16,  0, 60.0f);
        int e = b3d_init(px, dp, -1, 16, 60.0f);
        int f = b3d_init(px, dp, 16, 16, -1.0f);
        printf("nullpx=%d nulldp=%d w0=%d h0=%d wneg=%d fovneg=%d\n",
               a, b, c, d, e, f);

        size_t s1 = b3d_buffer_size(10, 10, sizeof(uint32_t));
        size_t s2 = b3d_buffer_size( 0, 10, sizeof(uint32_t));
        size_t s3 = b3d_buffer_size(10,  0, sizeof(uint32_t));
        size_t s4 = b3d_buffer_size(10, 10, 0);
        size_t s5 = b3d_buffer_size(-1, 10, sizeof(uint32_t));
        printf("bsz=%zu bsz_w0=%zu bsz_h0=%zu bsz_e0=%zu bsz_wneg=%zu\n",
               s1, s2, s3, s4, s5);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "nullpx=0 nulldp=0 w0=0 h0=0 wneg=0 fovneg=0" in r.stdout
    assert f"bsz={10 * 10 * 4} bsz_w0=0 bsz_h0=0 bsz_e0=0 bsz_wneg=0" in r.stdout


# ---------------------------------------------------------------------------
# Model matrix and transforms
# ---------------------------------------------------------------------------


def test_reset_produces_identity_matrix(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 60.0f)) return 1;

        /* Perturb the matrix, then reset */
        b3d_translate(3.0f, 4.0f, 5.0f);
        b3d_reset();

        float m[16];
        b3d_get_model_matrix(m);

        int is_ident = 1;
        for (int r = 0; r < 4; r++)
            for (int c = 0; c < 4; c++) {
                float want = (r == c) ? 1.0f : 0.0f;
                if (fabsf(m[r*4 + c] - want) > 1e-4f) is_ident = 0;
            }
        printf("identity=%d m00=%.3f m05=%.3f m10=%.3f m15=%.3f\n",
               is_ident, (double)m[0], (double)m[5], (double)m[10], (double)m[15]);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "identity=1 m00=1.000 m05=1.000 m10=1.000 m15=1.000" in r.stdout


def test_translate_and_scale_populate_matrix(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 60.0f)) return 1;

        b3d_reset();
        b3d_translate(1.0f, 2.0f, 3.0f);
        float m[16];
        b3d_get_model_matrix(m);
        printf("t_row3=%.3f,%.3f,%.3f\n", (double)m[12], (double)m[13], (double)m[14]);

        b3d_reset();
        b3d_scale(2.0f, 3.0f, 4.0f);
        b3d_get_model_matrix(m);
        printf("s_diag=%.3f,%.3f,%.3f\n", (double)m[0], (double)m[5], (double)m[10]);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "t_row3=1.000,2.000,3.000" in r.stdout
    assert "s_diag=2.000,3.000,4.000" in r.stdout


def test_rotate_axes_row_major_shape(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 60.0f)) return 1;

        float m[16];

        /* rotate_x(0.1) — populates m[5]/m[6]/m[9]/m[10] with cos/sin/-sin/cos */
        b3d_reset(); b3d_rotate_x(0.1f);
        b3d_get_model_matrix(m);
        printf("rx m5=%.3f m6=%.3f m9=%.3f m10=%.3f\n",
               (double)m[5], (double)m[6], (double)m[9], (double)m[10]);

        /* rotate_y(0.1) — populates m[0]/m[2]/m[8]/m[10] */
        b3d_reset(); b3d_rotate_y(0.1f);
        b3d_get_model_matrix(m);
        printf("ry m0=%.3f m2=%.3f m8=%.3f m10=%.3f\n",
               (double)m[0], (double)m[2], (double)m[8], (double)m[10]);

        /* rotate_z(0.1) — populates m[0]/m[1]/m[4]/m[5] */
        b3d_reset(); b3d_rotate_z(0.1f);
        b3d_get_model_matrix(m);
        printf("rz m0=%.3f m1=%.3f m4=%.3f m5=%.3f\n",
               (double)m[0], (double)m[1], (double)m[4], (double)m[5]);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    # cos(0.1) ~ 0.995, sin(0.1) ~ 0.100
    assert "rx m5=0.995 m6=0.100 m9=-0.100 m10=0.995" in r.stdout
    assert "ry m0=0.995 m2=0.100 m8=-0.100 m10=0.995" in r.stdout
    assert "rz m0=0.995 m1=0.100 m4=-0.100 m5=0.995" in r.stdout


def test_set_get_model_matrix_roundtrip(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        if (!b3d_init(px, dp, 16, 16, 60.0f)) return 1;

        float m_in[16] = {
             1.0f,  0.5f, -0.25f, 0.0f,
            -0.75f, 2.0f,  0.125f, 0.0f,
             0.0f,  0.0f,  3.0f,  0.0f,
             5.0f, 10.0f, 15.0f,  1.0f
        };
        b3d_set_model_matrix(m_in);

        float m_out[16];
        b3d_get_model_matrix(m_out);
        int ok = 1;
        for (int i = 0; i < 16; i++)
            if (fabsf(m_in[i] - m_out[i]) > 1e-5f) ok = 0;
        printf("roundtrip=%d t=%.3f,%.3f,%.3f\n",
               ok, (double)m_out[12], (double)m_out[13], (double)m_out[14]);

        /* Independence: setting the model matrix must not corrupt view/proj. */
        float v[16], p[16];
        b3d_get_view_matrix(v);
        b3d_get_proj_matrix(p);
        int view_col3_zero = (fabsf(v[3]) < 1e-4f) && (fabsf(v[7]) < 1e-4f)
                          && (fabsf(v[11]) < 1e-4f);
        int proj_last_col = (fabsf(p[3]) < 1e-4f) && (fabsf(p[7]) < 1e-4f);
        printf("view_col3=%d proj_col3=%d\n", view_col3_zero, proj_last_col);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "roundtrip=1 t=5.000,10.000,15.000" in r.stdout
    assert "view_col3=1 proj_col3=1" in r.stdout


def test_matrix_stack_push_pop_and_bounds(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        if (!b3d_init(px, dp, 16, 16, 60.0f)) return 1;

        b3d_reset();
        b3d_translate(1.0f, 0.0f, 0.0f);

        int p1 = b3d_push_matrix() ? 1 : 0;
        b3d_translate(2.0f, 0.0f, 0.0f);
        float m[16];
        b3d_get_model_matrix(m);
        printf("after_push_and_translate tx=%.3f push=%d\n", (double)m[12], p1);

        int p2 = b3d_pop_matrix() ? 1 : 0;
        b3d_get_model_matrix(m);
        printf("after_pop tx=%.3f pop=%d\n", (double)m[12], p2);

        /* Stack overflow: push more than B3D_MATRIX_STACK_SIZE = 16 */
        int fails = 0, tries = B3D_MATRIX_STACK_SIZE + 5;
        for (int i = 0; i < tries; i++)
            if (!b3d_push_matrix()) fails++;
        printf("push_fails_after_overflow=%d\n", fails);

        /* Stack underflow: pop until empty, then some more */
        int underflow = 0;
        for (int i = 0; i < tries + B3D_MATRIX_STACK_SIZE + 5; i++)
            if (!b3d_pop_matrix()) underflow++;
        printf("pop_fails_after_underflow>=1: %d\n", underflow >= 1 ? 1 : 0);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "after_push_and_translate tx=3.000 push=1" in r.stdout
    assert "after_pop tx=1.000 pop=1" in r.stdout
    # Must have observed at least 1 push failure once the 16-slot stack fills
    # (tries=21, at least 5 push_fails); and at least 1 pop failure once empty.
    assert "push_fails_after_overflow=5" in r.stdout
    assert "pop_fails_after_underflow>=1: 1" in r.stdout


# ---------------------------------------------------------------------------
# Camera, view, projection
# ---------------------------------------------------------------------------


def test_camera_set_get_roundtrip_and_view_matrix_changes(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 60.0f)) return 1;

        b3d_camera_t in_ = { 1.0f, 2.0f, 3.0f, 0.1f, 0.2f, 0.3f };
        b3d_set_camera(&in_);
        b3d_camera_t out_;
        b3d_get_camera(&out_);
        int rt =
            fabsf(out_.x    - in_.x   ) < 1e-4f &&
            fabsf(out_.y    - in_.y   ) < 1e-4f &&
            fabsf(out_.z    - in_.z   ) < 1e-4f &&
            fabsf(out_.yaw  - in_.yaw ) < 1e-4f &&
            fabsf(out_.pitch- in_.pitch)< 1e-4f &&
            fabsf(out_.roll - in_.roll) < 1e-4f;
        printf("cam_roundtrip=%d\n", rt);

        /* For a camera at (3,5,7) with no rotation, the view matrix
         * translation row (m[12..14]) must encode the inverse of the
         * camera translation: (-3, -5, -7). Any impl that just stores
         * the camera fields but doesn't build a real view matrix will
         * fail this check. The tolerance is deliberately loose: this
         * checks the inversion, not trig precision: a coordinate of
         * magnitude 7 amplifies the documented trig error budget. */
        b3d_camera_t no_rot = { 3.0f, 5.0f, 7.0f, 0, 0, 0 };
        b3d_set_camera(&no_rot);
        float v1[16];
        b3d_get_view_matrix(v1);
        int view_translation_ok =
            fabsf(v1[12] - (-3.0f)) < 1e-2f &&
            fabsf(v1[13] - (-5.0f)) < 1e-2f &&
            fabsf(v1[14] - (-7.0f)) < 1e-2f;
        printf("view_tx_ok=%d v[12/13/14]=%.3f,%.3f,%.3f\n",
               view_translation_ok,
               (double)v1[12], (double)v1[13], (double)v1[14]);

        /* Restore original camera so later look_at check runs against it. */
        b3d_set_camera(&in_);

        /* look_at rebuilds the view without touching stored position */
        b3d_look_at(5.0f, 6.0f, 7.0f);
        b3d_get_camera(&out_);
        int pos_unchanged =
            fabsf(out_.x - in_.x) < 1e-4f &&
            fabsf(out_.y - in_.y) < 1e-4f &&
            fabsf(out_.z - in_.z) < 1e-4f;
        printf("pos_after_lookat_unchanged=%d\n", pos_unchanged);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "cam_roundtrip=1" in r.stdout
    assert "view_tx_ok=1" in r.stdout
    assert "pos_after_lookat_unchanged=1" in r.stdout


def test_fov_roundtrip_and_perspective_matrix(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 60.0f)) return 1;

        b3d_set_fov(90.0f);
        printf("fov=%.1f ortho=%d\n", (double)b3d_get_fov(), (int)b3d_is_ortho());

        float p[16];
        b3d_get_proj_matrix(p);
        /* Perspective projection: last-column shape is (0,0,1,0) — i.e.
         * m[3]=m[7]=m[15]=0 and |m[11]|=1 (the perspective divide row). */
        int shape =
            fabsf(p[3])       < 1e-4f &&
            fabsf(p[7])       < 1e-4f &&
            fabsf(fabsf(p[11]) - 1.0f) < 1e-4f &&
            fabsf(p[15])      < 1e-4f;
        printf("persp_shape=%d\n", shape);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "fov=90.0 ortho=0" in r.stdout
    assert "persp_shape=1" in r.stdout


def test_ortho_toggle_and_matrix_shape(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 60.0f)) return 1;

        printf("boot_ortho=%d\n", (int)b3d_is_ortho());
        b3d_ortho(-2.0f, 2.0f, -1.5f, 1.5f, 0.1f, 50.0f);
        printf("after_ortho=%d\n", (int)b3d_is_ortho());

        float p[16];
        b3d_get_proj_matrix(p);
        /* Orthographic proj: last-column shape is (0, 0, 0, 1). */
        int shape =
            fabsf(p[3])        < 1e-4f &&
            fabsf(p[7])        < 1e-4f &&
            fabsf(p[11])       < 1e-4f &&
            fabsf(p[15] - 1.0f)< 1e-4f;
        printf("ortho_shape=%d\n", shape);

        /* set_fov must switch back to perspective */
        b3d_set_fov(60.0f);
        printf("after_set_fov=%d\n", (int)b3d_is_ortho());
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "boot_ortho=0" in r.stdout
    assert "after_ortho=1" in r.stdout
    assert "ortho_shape=1" in r.stdout
    assert "after_set_fov=0" in r.stdout


# ---------------------------------------------------------------------------
# Rendering: triangles, culling, depth
# ---------------------------------------------------------------------------


def _pixel_count_helper():
    """Emits a C helper that counts non-zero pixels in the framebuffer."""
    return r"""
    static size_t count_nonzero(const uint32_t *pixels, int w, int h) {
        size_t n = 0;
        for (int i = 0; i < w * h; i++)
            if (pixels[i] != 0) n++;
        return n;
    }
    """


def test_triangle_visible_returns_true_and_paints_pixels(build_and_run):
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -5, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        b3d_tri_t t = {{
            {-0.5f, -0.5f, 0.0f},
            {0.0f,  0.5f, 0.0f},
            {0.5f, -0.5f, 0.0f}
        }};
        int drew = b3d_triangle(&t, 0xff8800) ? 1 : 0;
        size_t n = count_nonzero(px, 64, 64);
        /* World (0,0,0) projects to screen center (32,32) and lies inside the
         * triangle, so the flat color 0xff8800 must be written there. */
        uint32_t center = px[64/2 * 64 + 64/2] & 0xffffffu;
        printf("drew=%d nonzero>0=%d center=0x%06x\n",
               drew, n > 0 ? 1 : 0, (unsigned)center);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "drew=1 nonzero>0=1 center=0xff8800" in r.stdout


def test_clear_resets_pixels_and_drop_count(build_and_run):
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        b3d_tri_t t = {{
            {-0.5f, -0.5f, 0.0f},
            {0.0f,  0.5f, 0.0f},
            {0.5f, -0.5f, 0.0f}
        }};
        b3d_triangle(&t, 0xffffff);
        size_t before = count_nonzero(px, 32, 32);
        b3d_clear();
        size_t after = count_nonzero(px, 32, 32);
        printf("before>0=%d after=%zu drop=%zu\n",
               before > 0 ? 1 : 0, after, b3d_get_clip_drop_count());
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "before>0=1 after=0 drop=0" in r.stdout


def test_backface_culling_and_draw_backface_flag(build_and_run):
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -5, 0, 0, 0});
        b3d_reset();

        /* Front-face (CCW from camera) — should render. */
        b3d_tri_t front = {{
            {-0.5f, -0.5f, 0.0f},
            {0.0f,  0.5f, 0.0f},
            {0.5f, -0.5f, 0.0f}
        }};
        b3d_clear();
        int drew_front = b3d_triangle(&front, 0x00ff00) ? 1 : 0;
        size_t front_px = count_nonzero(px, 64, 64);

        /* Back-face (reversed winding) — should be culled by default. */
        b3d_tri_t back = {{
            {0.5f, -0.5f, 0.0f},
            {0.0f,  0.5f, 0.0f},
            {-0.5f, -0.5f, 0.0f}
        }};
        b3d_clear();
        int drew_back = b3d_triangle(&back, 0xff0000) ? 1 : 0;
        size_t back_px = count_nonzero(px, 64, 64);

        /* Back-face with B3D_DRAW_BACKFACE flag — should render anyway, and
         * rasterize the same footprint as the front-face of the same shape
         * (flag only bypasses culling; the triangle is otherwise identical),
         * so flagged/front pixel count is ~1.0 (accept 0.7-1.3). */
        b3d_clear();
        int drew_flagged = b3d_triangle(&back, 0xff0000 | B3D_DRAW_BACKFACE) ? 1 : 0;
        size_t flagged_px = count_nonzero(px, 64, 64);

        int ratio_ok = 0;
        if (front_px > 0 && flagged_px > 0) {
            double rr = (double)flagged_px / (double)front_px;
            if (rr > 0.7 && rr < 1.3) ratio_ok = 1;
        }

        printf("front=%d fpx>0=%d back=%d bpx=%zu flagged=%d flagpx>0=%d ratio_ok=%d\n",
               drew_front, front_px > 0 ? 1 : 0,
               drew_back,  back_px,
               drew_flagged, flagged_px > 0 ? 1 : 0, ratio_ok);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "front=1 fpx>0=1 back=0 bpx=0 flagged=1 flagpx>0=1 ratio_ok=1" in r.stdout


def test_depth_buffer_reset_across_clear(build_and_run):
    """b3d_clear resets the depth buffer to the far-plane value (not only the
    pixels). Draw a NEAR triangle, then b3d_clear, then a FARTHER triangle over
    the same region: because the depth buffer was reset to far, the farther
    triangle passes the depth test and paints. An impl that clears pixels but
    leaves stale near depths would reject the farther fragment and the center
    would stay unpainted. (Multi-layer near-wins ordering is covered separately
    by test_R10_depth_three_layers_middle_wins_at_edge.)"""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -5, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        /* NEAR red triangle at z=0 writes the center pixel and its depth. */
        b3d_tri_t near_tri = {{
            {-0.5f, -0.5f, 0.0f},
            {0.0f,  0.5f, 0.0f},
            {0.5f, -0.5f, 0.0f}
        }};
        b3d_triangle(&near_tri, 0xff0000);
        uint32_t center_near = px[64/2 * 64 + 64/2] & 0xffffffu;

        /* Clear: pixels -> 0 and the depth buffer -> far-plane value. */
        b3d_clear();
        uint32_t center_cleared = px[64/2 * 64 + 64/2] & 0xffffffu;

        /* FARTHER green triangle at z=0.5 over the same center. It sits behind
         * where the near triangle was, so it paints only if b3d_clear actually
         * reset the depth buffer. */
        b3d_tri_t far_tri = {{
            {-1.0f, -1.0f, 0.5f},
            {0.0f,   1.5f, 0.5f},
            {1.0f,  -1.0f, 0.5f}
        }};
        b3d_triangle(&far_tri, 0x00ff00);
        uint32_t center_far = px[64/2 * 64 + 64/2] & 0xffffffu;

        printf("near=0x%06x cleared=0x%06x far_after_clear=0x%06x\n",
               (unsigned)center_near, (unsigned)center_cleared,
               (unsigned)center_far);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "near=0xff0000 cleared=0x000000 far_after_clear=0x00ff00" in r.stdout


def test_nonfinite_and_degenerate_triangles_rejected(build_and_run):
    driver = (
        r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_clear();

        /* Contains NaN — must be rejected. */
        b3d_tri_t nan_tri = {{
            {NAN, 0.0f, 0.0f},
            {1.0f, 0.0f, 0.0f},
            {0.0f, 1.0f, 0.0f}
        }};
        int nan_r = b3d_triangle(&nan_tri, 0xffffff) ? 1 : 0;

        /* Contains +Inf — must be rejected. */
        b3d_tri_t inf_tri = {{
            {0.0f, 0.0f, 0.0f},
            {INFINITY, 0.0f, 0.0f},
            {0.0f, 1.0f, 0.0f}
        }};
        int inf_r = b3d_triangle(&inf_tri, 0xffffff) ? 1 : 0;

        /* NULL pointer — must return false. */
        int null_r = b3d_triangle(NULL, 0xffffff) ? 1 : 0;

        /* Degenerate collinear triangle — no pixels produced. */
        b3d_tri_t line_tri = {{
            {0.0f, 0.0f, 0.5f},
            {0.5f, 0.0f, 0.5f},
            {1.0f, 0.0f, 0.5f}
        }};
        b3d_triangle(&line_tri, 0xffffff);
        size_t after = count_nonzero(px, 32, 32);
        printf("nan=%d inf=%d null=%d line_px=%zu\n",
               nan_r, inf_r, null_r, after);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "nan=0 inf=0 null=0 line_px=0" in r.stdout


# ---------------------------------------------------------------------------
# Clipping
# ---------------------------------------------------------------------------


def test_near_plane_clip_behind_and_straddle(build_and_run):
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, 0, 0, 0, 0});
        b3d_reset();

        /* Fully behind near plane (z < 0.1). */
        b3d_tri_t behind = {{
            {-0.5f, -0.5f, 0.05f},
            {0.0f,  0.5f, 0.05f},
            {0.5f, -0.5f, 0.05f}
        }};
        b3d_clear();
        int rb = b3d_triangle(&behind, 0xff0000) ? 1 : 0;
        size_t nb = count_nonzero(px, 64, 64);

        /* Straddling near plane. */
        b3d_tri_t straddle = {{
            {-0.5f, -0.5f, 0.05f},
            {0.0f,  0.5f, 0.2f},
            {0.5f, -0.5f, 0.2f}
        }};
        b3d_clear();
        int rs = b3d_triangle(&straddle, 0x0000ff) ? 1 : 0;
        size_t ns = count_nonzero(px, 64, 64);

        printf("behind=%d bpx=%zu straddle=%d spx>0=%d\n",
               rb, nb, rs, ns > 0 ? 1 : 0);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "behind=0 bpx=0 straddle=1 spx>0=1" in r.stdout


def test_far_plane_clip_beyond_and_straddle(build_and_run):
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, 0, 0, 0, 0});
        b3d_reset();

        /* Fully beyond far plane (z > 100). */
        b3d_tri_t beyond = {{
            {-10.0f, -10.0f, 150.0f},
            {0.0f,  10.0f, 150.0f},
            {10.0f, -10.0f, 150.0f}
        }};
        b3d_clear();
        int rb = b3d_triangle(&beyond, 0xff0000) ? 1 : 0;
        size_t nb = count_nonzero(px, 64, 64);

        /* Straddling far plane. */
        b3d_tri_t straddle = {{
            {-10.0f, -10.0f, 90.0f},
            {0.0f,  10.0f, 110.0f},
            {10.0f, -10.0f, 90.0f}
        }};
        b3d_clear();
        int rs = b3d_triangle(&straddle, 0x0000ff) ? 1 : 0;
        size_t ns = count_nonzero(px, 64, 64);

        printf("beyond=%d bpx=%zu straddle=%d spx>0=%d\n",
               rb, nb, rs, ns > 0 ? 1 : 0);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "beyond=0 bpx=0 straddle=1 spx>0=1" in r.stdout


# ---------------------------------------------------------------------------
# Lighting
# ---------------------------------------------------------------------------


def test_light_direction_default_and_normalization(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        if (!b3d_init(px, dp, 16, 16, 60.0f)) return 1;

        /* Default light direction is +Z */
        float x, y, z;
        b3d_get_light_direction(&x, &y, &z);
        printf("def=%.3f,%.3f,%.3f\n", (double)x, (double)y, (double)z);

        /* Setter normalizes */
        b3d_set_light_direction(1.0f, 1.0f, 1.0f);
        b3d_get_light_direction(&x, &y, &z);
        float expected = 1.0f / sqrtf(3.0f);
        int norm_ok =
            fabsf(x - expected) < 0.01f &&
            fabsf(y - expected) < 0.01f &&
            fabsf(z - expected) < 0.01f;
        printf("norm_ok=%d\n", norm_ok);

        /* Zero-length input keeps previous direction */
        b3d_set_light_direction(0.0f, 0.0f, 0.0f);
        b3d_get_light_direction(&x, &y, &z);
        int kept = fabsf(x - expected) < 0.01f;
        printf("zero_rejected=%d\n", kept);

        /* NaN input keeps previous direction */
        b3d_set_light_direction(NAN, 0.0f, 1.0f);
        b3d_get_light_direction(&x, &y, &z);
        int kept2 = fabsf(x - expected) < 0.01f;
        printf("nan_rejected=%d\n", kept2);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "def=0.000,0.000,1.000" in r.stdout
    assert "norm_ok=1" in r.stdout
    assert "zero_rejected=1" in r.stdout
    assert "nan_rejected=1" in r.stdout


def test_ambient_get_set_and_clamp(build_and_run):
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        if (!b3d_init(px, dp, 16, 16, 60.0f)) return 1;

        printf("default=%.3f\n", (double)b3d_get_ambient());

        b3d_set_ambient(0.5f);
        printf("mid=%.3f\n", (double)b3d_get_ambient());

        /* Clamp negative → 0 */
        b3d_set_ambient(-0.5f);
        printf("neg=%.3f\n", (double)b3d_get_ambient());

        /* Clamp > 1 → 1 */
        b3d_set_ambient(1.7f);
        printf("hi=%.3f\n", (double)b3d_get_ambient());

        /* NaN rejected — keeps previous 1.0 */
        b3d_set_ambient(NAN);
        printf("nan_kept=%.3f\n", (double)b3d_get_ambient());
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "default=0.200" in r.stdout
    assert "mid=0.500" in r.stdout
    assert "neg=0.000" in r.stdout
    assert "hi=1.000" in r.stdout
    assert "nan_kept=1.000" in r.stdout


def test_triangle_lit_intensity_scaling(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -2, 0, 0, 0});
        b3d_reset();
        b3d_set_ambient(0.2f);

        /* Light aligned WITH normal → |dot| = 1 → intensity = 1 → full color. */
        b3d_set_light_direction(0.0f, 0.0f, 1.0f);
        b3d_clear();
        b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, -1.0f, 0xffffff);
        uint32_t full = px[64/2 * 64 + 64/2];

        /* Light PERPENDICULAR to normal → |dot| = 0 → intensity = ambient = 0.2
         * → each channel ~ 0x33 (0.2 * 255 = 51). */
        b3d_set_light_direction(1.0f, 0.0f, 0.0f);
        b3d_clear();
        b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, -1.0f, 0xffffff);
        uint32_t amb = px[64/2 * 64 + 64/2];
        unsigned r = (amb >> 16) & 0xff, g = (amb >> 8) & 0xff, b = amb & 0xff;
        int in_range = (r >= 45 && r <= 60) && (g >= 45 && g <= 60) && (b >= 45 && b <= 60);
        printf("full=0x%06x amb=0x%02x%02x%02x amb_ok=%d\n",
               (unsigned)full & 0xffffffu, r, g, b, in_range);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "full=0xffffff" in r.stdout
    assert "amb_ok=1" in r.stdout


# ---------------------------------------------------------------------------
# Screen projection
# ---------------------------------------------------------------------------


def test_to_screen_center_projection_and_behind_camera(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, 0, 0, 0, 0});

        int sx = -1, sy = -1;
        /* Point in front of camera along +Z projects near screen center. */
        int r_front = b3d_to_screen(0.0f, 0.0f, 1.0f, &sx, &sy) ? 1 : 0;
        int centered =
            sx >= 64/2 - 2 && sx <= 64/2 + 2 &&
            sy >= 64/2 - 2 && sy <= 64/2 + 2;
        printf("front=%d centered=%d\n", r_front, centered);

        /* Point behind camera returns false. */
        int r_back = b3d_to_screen(0.0f, 0.0f, -1.0f, &sx, &sy) ? 1 : 0;
        printf("back=%d\n", r_back);

        /* NULL output pointers → false. */
        int r_nx = b3d_to_screen(0, 0, 1, NULL, &sy) ? 1 : 0;
        int r_ny = b3d_to_screen(0, 0, 1, &sx, NULL) ? 1 : 0;
        printf("null_sx=%d null_sy=%d\n", r_nx, r_ny);

        /* Point to the right → sx > center. */
        r_front = b3d_to_screen(1.0f, 0.0f, 1.0f, &sx, &sy) ? 1 : 0;
        int right = sx > 64/2;
        /* Point above (+Y) → sy < center (screen y flipped). */
        int r_top = b3d_to_screen(0.0f, 1.0f, 1.0f, &sx, &sy) ? 1 : 0;
        int above = sy < 64/2;
        printf("right=%d top=%d\n", right && r_front, above && r_top);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "front=1 centered=1" in r.stdout
    assert "back=0" in r.stdout
    assert "null_sx=0 null_sy=0" in r.stdout
    assert "right=1 top=1" in r.stdout


# ---------------------------------------------------------------------------
# Orthographic rendering
# ---------------------------------------------------------------------------


def test_ortho_mode_depth_test(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 60.0f)) return 1;
        b3d_ortho(-1.0f, 1.0f, -1.0f, 1.0f, 0.1f, 100.0f);
        b3d_set_camera(&(b3d_camera_t){0, 0, -5, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        /* Far green triangle. */
        b3d_triangle(&(b3d_tri_t){{
            {-0.8f, -0.8f, 0.5f},
            {0.0f,  0.8f, 0.5f},
            {0.8f, -0.8f, 0.5f}
        }}, 0x00ff00);

        /* Near red triangle. */
        b3d_triangle(&(b3d_tri_t){{
            {-0.4f, -0.4f, 0.0f},
            {0.0f,  0.4f, 0.0f},
            {0.4f, -0.4f, 0.0f}
        }}, 0xff0000);

        uint32_t center = px[64/2 * 64 + 64/2];
        printf("center=0x%06x\n", (unsigned)center & 0xffffffu);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "center=0xff0000" in r.stdout


# ---------------------------------------------------------------------------
# b3d-math wrappers
# ---------------------------------------------------------------------------


def test_b3d_math_wrappers_default_mode(build_and_run):
    """Fixed-point wrappers must match sinf/cosf/sqrtf within LUT accuracy
    (the spec documents ~1e-4; this is a loose 0.02 smoke check)."""
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <b3d-math.h>
    int main(void) {
        int sin_ok  = fabsf(b3d_sinf(0.0f))              < 0.02f
                   && fabsf(b3d_sinf(1.5707963f) - 1.0f) < 0.02f
                   && fabsf(b3d_sinf(3.1415927f))        < 0.02f
                   && fabsf(b3d_sinf(-1.5707963f) + 1.0f)< 0.02f;

        int cos_ok  = fabsf(b3d_cosf(0.0f) - 1.0f)       < 0.02f
                   && fabsf(b3d_cosf(1.5707963f))        < 0.02f
                   && fabsf(b3d_cosf(3.1415927f) + 1.0f) < 0.02f;

        int sqrt_ok = fabsf(b3d_sqrtf(4.0f) - 2.0f)      < 0.01f
                   && fabsf(b3d_sqrtf(2.0f) - 1.4142f)   < 0.01f
                   && b3d_sqrtf(-1.0f) == 0.0f
                   && b3d_sqrtf(0.0f)  == 0.0f;

        int abs_ok  = b3d_fabsf(5.0f)  == 5.0f
                   && b3d_fabsf(-5.0f) == 5.0f
                   && b3d_fabsf(0.0f)  == 0.0f;

        float s = -99, c = -99;
        b3d_sincosf(0.7853982f, &s, &c);  /* pi/4 */
        int sc_ok = fabsf(s - 0.7071f) < 0.02f && fabsf(c - 0.7071f) < 0.02f;

        printf("sin=%d cos=%d sqrt=%d abs=%d sincos=%d\n",
               sin_ok, cos_ok, sqrt_ok, abs_ok, sc_ok);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "sin=1 cos=1 sqrt=1 abs=1 sincos=1" in r.stdout


def test_b3d_math_wrappers_float_point_mode(build_and_run):
    """Floating-point mode wrappers must match sinf/cosf exactly (tight
    tolerance). Compiled with -DB3D_FLOAT_POINT; does NOT include <b3d.h>
    so the b3d_depth_t typedef change does not leak into the driver."""
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <b3d-math.h>
    int main(void) {
        int sin_ok  = fabsf(b3d_sinf(0.0f))              < 1e-4f
                   && fabsf(b3d_sinf(1.5707963f) - 1.0f) < 1e-4f
                   && fabsf(b3d_sinf(3.1415927f))        < 1e-4f;

        int cos_ok  = fabsf(b3d_cosf(0.0f) - 1.0f)       < 1e-4f
                   && fabsf(b3d_cosf(1.5707963f))        < 1e-4f;

        int tan_ok  = fabsf(b3d_tanf(0.7853982f) - 1.0f) < 1e-3f
                   && b3d_tanf(1.5707963f * 0.999999f) != INFINITY;

        int sqrt_ok = fabsf(b3d_sqrtf(9.0f) - 3.0f)      < 1e-4f
                   && b3d_sqrtf(-2.0f) == 0.0f;

        float s = 0, c = 0;
        b3d_sincosf(0.7853982f, &s, &c);
        int sc_ok = fabsf(s - 0.70710678f) < 1e-4f
                 && fabsf(c - 0.70710678f) < 1e-4f;

        printf("sin=%d cos=%d tan=%d sqrt=%d sincos=%d\n",
               sin_ok, cos_ok, tan_ok, sqrt_ok, sc_ok);
        return 0;
    }
    """
    r = build_and_run(driver, extra_cflags=("-DB3D_FLOAT_POINT",))
    assert r.returncode == 0
    assert "sin=1 cos=1 tan=1 sqrt=1 sincos=1" in r.stdout


# ---------------------------------------------------------------------------
# OBJ loader
# ---------------------------------------------------------------------------


def test_load_obj_triangle_mesh_basic(build_and_run, tmp_path):
    obj = tmp_path / "tri.obj"
    obj.write_text(
        "# a lone triangle\n"
        "v 0.0 0.0 0.0\n"
        "v 1.0 0.0 0.0\n"
        "v 0.0 1.0 0.0\n"
        "f 1 2 3\n"
    )
    driver = r"""
    #include <stdio.h>
    #include <b3d-obj.h>
    int main(int argc, char **argv) {
        b3d_mesh_t m = {0};
        int rc = b3d_load_obj(argv[1], &m);
        if (rc != 0) { printf("rc=%d\n", rc); return 0; }
        printf("rc=%d tri=%d vc=%d p0=%.1f,%.1f,%.1f p1=%.1f,%.1f,%.1f p2=%.1f,%.1f,%.1f\n",
               rc, m.triangle_count, m.vertex_count,
               (double)m.triangles[0], (double)m.triangles[1], (double)m.triangles[2],
               (double)m.triangles[3], (double)m.triangles[4], (double)m.triangles[5],
               (double)m.triangles[6], (double)m.triangles[7], (double)m.triangles[8]);
        b3d_free_mesh(&m);
        printf("after_free tri=%d vc=%d\n", m.triangle_count, m.vertex_count);
        return 0;
    }
    """
    r = build_and_run(driver, argv=[str(obj)])
    assert r.returncode == 0
    assert "rc=0 tri=1 vc=9 p0=0.0,0.0,0.0 p1=1.0,0.0,0.0 p2=0.0,1.0,0.0" in r.stdout
    assert "after_free tri=0 vc=0" in r.stdout


def test_load_obj_fan_triangulation_face_formats(build_and_run, tmp_path):
    obj = tmp_path / "quad.obj"
    # A 4-vertex quad fan-triangulates into 2 triangles (0,1,2) + (0,2,3).
    # Also uses v/vt, v/vt/vn, and v//vn face formats to exercise the parser.
    obj.write_text(
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 1 1 0\n"
        "v 0 1 0\n"
        "vn 0 0 1\n"
        "vt 0 0\n"
        "f 1/1 2/1 3/1/1 4//1\n"
    )
    driver = r"""
    #include <stdio.h>
    #include <b3d-obj.h>
    int main(int argc, char **argv) {
        b3d_mesh_t m = {0};
        int rc = b3d_load_obj(argv[1], &m);
        printf("rc=%d tri=%d\n", rc, m.triangle_count);
        if (m.triangle_count == 2) {
            /* Tri 0: verts 0,1,2. Tri 1: verts 0,2,3. */
            printf("t0=(%.1f,%.1f)-(%.1f,%.1f)-(%.1f,%.1f) "
                   "t1=(%.1f,%.1f)-(%.1f,%.1f)-(%.1f,%.1f)\n",
                   (double)m.triangles[0], (double)m.triangles[1],
                   (double)m.triangles[3], (double)m.triangles[4],
                   (double)m.triangles[6], (double)m.triangles[7],
                   (double)m.triangles[9],  (double)m.triangles[10],
                   (double)m.triangles[12], (double)m.triangles[13],
                   (double)m.triangles[15], (double)m.triangles[16]);
        }
        b3d_free_mesh(&m);
        return 0;
    }
    """
    r = build_and_run(driver, argv=[str(obj)])
    assert r.returncode == 0
    assert "rc=0 tri=2" in r.stdout
    assert (
        "t0=(0.0,0.0)-(1.0,0.0)-(1.0,1.0) t1=(0.0,0.0)-(1.0,1.0)-(0.0,1.0)" in r.stdout
    )


def test_load_obj_negative_indices_and_exponent(build_and_run, tmp_path):
    obj = tmp_path / "neg.obj"
    # Negative indices (relative to current vertex count) and scientific
    # notation in a coordinate.
    obj.write_text("v 0 0 0\n" "v 1 0 0\n" "v 0.5 1.5e0 0\n" "f -3 -2 -1\n")
    driver = r"""
    #include <stdio.h>
    #include <b3d-obj.h>
    int main(int argc, char **argv) {
        b3d_mesh_t m = {0};
        int rc = b3d_load_obj(argv[1], &m);
        printf("rc=%d tri=%d\n", rc, m.triangle_count);
        if (m.triangle_count == 1) {
            printf("p2=(%.2f,%.2f)\n",
                   (double)m.triangles[6], (double)m.triangles[7]);
        }
        b3d_free_mesh(&m);
        return 0;
    }
    """
    r = build_and_run(driver, argv=[str(obj)])
    assert r.returncode == 0
    assert "rc=0 tri=1" in r.stdout
    # p2 should be the 3rd vertex (0.5, 1.5)
    assert "p2=(0.50,1.50)" in r.stdout


def test_load_obj_missing_file_returns_1(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <b3d-obj.h>
    int main(void) {
        b3d_mesh_t m = {0};
        int rc = b3d_load_obj("/tmp/does_not_exist_xyzzy_9999.obj", &m);
        printf("rc=%d tri=%d\n", rc, m.triangle_count);

        rc = b3d_load_obj(NULL, &m);
        printf("nullpath_rc=%d\n", rc);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "rc=1 tri=0" in r.stdout
    assert "nullpath_rc=1" in r.stdout


def test_mesh_bounds_min_max_xz(build_and_run, tmp_path):
    obj = tmp_path / "cube.obj"
    # 8 vertices of a unit cube centered at (0.5, 0.5, 0.5) — extents 0..1.
    obj.write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "v 0 0 1\nv 1 0 1\nv 1 1 1\nv 0 1 1\n"
        "f 1 2 3\nf 1 3 4\n"
        "f 5 6 7\nf 5 7 8\n"
    )
    driver = r"""
    #include <stdio.h>
    #include <b3d-obj.h>
    int main(int argc, char **argv) {
        b3d_mesh_t m = {0};
        int rc = b3d_load_obj(argv[1], &m);
        float miny = -99, maxy = -99, maxxz = -99;
        b3d_mesh_bounds(&m, &miny, &maxy, &maxxz);
        printf("rc=%d miny=%.2f maxy=%.2f maxxz=%.2f\n",
               rc, (double)miny, (double)maxy, (double)maxxz);

        /* NULL-safe: all three pointers may be NULL */
        b3d_mesh_bounds(&m, NULL, NULL, NULL);

        /* Empty mesh writes 0s */
        b3d_mesh_t empty = {0};
        miny = maxy = maxxz = 7.0f;
        b3d_mesh_bounds(&empty, &miny, &maxy, &maxxz);
        printf("empty miny=%.1f maxy=%.1f maxxz=%.1f\n",
               (double)miny, (double)maxy, (double)maxxz);
        b3d_free_mesh(&m);
        return 0;
    }
    """
    r = build_and_run(driver, argv=[str(obj)])
    assert r.returncode == 0
    # Bounds cover 0..1 in y and 0..1 in x/z (max_xz = 1)
    assert "rc=0 miny=0.00 maxy=1.00 maxxz=1.00" in r.stdout
    assert "empty miny=0.0 maxy=0.0 maxxz=0.0" in r.stdout


# ---------------------------------------------------------------------------
# Voxelizer
# ---------------------------------------------------------------------------


def test_voxel_mesh_aabb_matches_input(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <b3d-voxel.h>
    int main(void) {
        /* Two triangles spanning (-1..5) x (-2..8) x (0..9) */
        float tris[] = {
            -1.0f, -2.0f, 0.0f,
             2.0f,  3.0f, 4.5f,
             5.0f, -1.0f, 9.0f,
             1.0f,  8.0f, 3.0f,
             0.0f, -2.0f, 0.0f,
             4.0f,  0.0f, 2.0f,
        };
        b3d_aabb_t box = {{0,0,0},{0,0,0}};
        b3d_voxel_mesh_aabb(tris, 2, &box);
        printf("min=%.1f,%.1f,%.1f max=%.1f,%.1f,%.1f\n",
               (double)box.min.x, (double)box.min.y, (double)box.min.z,
               (double)box.max.x, (double)box.max.y, (double)box.max.z);

        /* NULL / zero-count safe */
        b3d_aabb_t box2 = {{7,7,7},{7,7,7}};
        b3d_voxel_mesh_aabb(NULL, 2, &box2);
        b3d_voxel_mesh_aabb(tris, 0, &box2);
        b3d_voxel_mesh_aabb(tris, 2, NULL);
        printf("untouched=%.1f,%.1f,%.1f\n",
               (double)box2.min.x, (double)box2.min.y, (double)box2.min.z);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "min=-1.0,-2.0,0.0 max=5.0,8.0,9.0" in r.stdout
    assert "untouched=7.0,7.0,7.0" in r.stdout


def test_voxelize_estimation_and_produce(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <b3d-voxel.h>
    int main(void) {
        /* A single 2x2x0 triangle in the xy plane, voxel size 0.5.
         * The triangle covers ~2 units in x and y — at voxel_size=0.5 we
         * expect a small but non-zero number of voxel overlaps.
         */
        float tris[] = {
             0.0f, 0.0f, 0.0f,
             2.0f, 0.0f, 0.0f,
             0.0f, 2.0f, 0.0f,
        };

        /* Estimation mode: NULL output, returns upper bound.
         * For a right-triangle covering ~2x2 units in the xy plane with
         * voxel_size=0.5, a plausible impl produces roughly 10-40 voxel
         * candidates (the plane-crossings, not the fill). */
        size_t est = b3d_voxelize(tris, 1, 0.5f, 0xff0000, NULL, 0);
        int est_in_range = (est >= 10 && est <= 40) ? 1 : 0;
        printf("est=%zu est_in_range=%d\n", est, est_in_range);

        /* Produce mode: unique count after dedup should be in [8, 30]. */
        b3d_voxel_t out[512];
        size_t unique = b3d_voxelize(tris, 1, 0.5f, 0xff0000, out, 512);
        int unique_in_range = (unique >= 8 && unique <= 30) ? 1 : 0;
        printf("unique=%zu unique_in_range=%d unique<=est=%d\n",
               unique, unique_in_range, unique <= est ? 1 : 0);

        /* Bad inputs → 0. */
        size_t z1 = b3d_voxelize(NULL,  1, 0.5f, 0, out, 512);
        size_t z2 = b3d_voxelize(tris,  0, 0.5f, 0, out, 512);
        size_t z3 = b3d_voxelize(tris,  1, 0.0f, 0, out, 512);
        size_t z4 = b3d_voxelize(tris,  1, -1.f, 0, out, 512);
        printf("bad=%zu,%zu,%zu,%zu\n", z1, z2, z3, z4);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "est_in_range=1" in r.stdout
    assert "unique_in_range=1" in r.stdout
    assert "unique<=est=1" in r.stdout
    assert "bad=0,0,0,0" in r.stdout


def test_voxelize_overflow_indicator(build_and_run):
    driver = r"""
    #include <stdio.h>
    #include <b3d-voxel.h>
    int main(void) {
        /* Large triangle → many voxels — set max_voxels tiny to force overflow. */
        float tris[] = {
             0.0f, 0.0f, 0.0f,
            10.0f, 0.0f, 0.0f,
             0.0f,10.0f, 0.0f,
        };
        b3d_voxel_t out[4];
        size_t n = b3d_voxelize(tris, 1, 0.5f, 0xffffff, out, 4);
        /* Overflow indicator is max_voxels + 1. */
        printf("n=%zu overflow=%d\n", n, n == 5 ? 1 : 0);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "overflow=1" in r.stdout


def test_voxel_render_paints_pixels(build_and_run):
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    #include <b3d-voxel.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -4, 0, 0, 0});
        b3d_reset();
        b3d_set_ambient(1.0f);  /* full ambient — lit color = base color */
        b3d_set_light_direction(0, 0, 1);

        b3d_voxel_t v[1] = {{{0.0f, 0.0f, 0.0f}, 0xff8800}};

        b3d_clear();
        b3d_voxel_render(v, 1, 1.0f);
        size_t lit_px = count_nonzero(px, 64, 64);
        uint32_t lit_center = px[32*64 + 32] & 0xffffffu;

        b3d_clear();
        b3d_voxel_render_flat(v, 1, 1.0f);
        size_t flat_px = count_nonzero(px, 64, 64);
        uint32_t flat_center = px[32*64 + 32] & 0xffffffu;

        /* With ambient=1 and full color, both lit and flat should paint the
         * front face of a unit voxel to base color 0xff8800. Viewed head-on
         * from z=-4 with fov=65, only the front face is visible: the 4 side
         * faces are edge-on/back-facing and culled, and the back face is
         * occluded. That single ~14x14 face covers ~196 px, so accept a
         * lenient [150,400] band (cf. test_R1's [100,400] for a comparable
         * face) rather than a tight floor that depends on the unspecified
         * sub-pixel fill convention. */
        int lit_range_ok = (lit_px >= 150 && lit_px <= 400) ? 1 : 0;
        int flat_range_ok = (flat_px >= 150 && flat_px <= 400) ? 1 : 0;
        printf("lit_px=%zu lit_center=0x%06x lit_range=%d\n",
               lit_px, (unsigned)lit_center, lit_range_ok);
        printf("flat_px=%zu flat_center=0x%06x flat_range=%d\n",
               flat_px, (unsigned)flat_center, flat_range_ok);

        /* Bad inputs are no-ops (do not crash, produce no output). */
        b3d_clear();
        b3d_voxel_render(NULL, 1, 1.0f);
        b3d_voxel_render(v,    0, 1.0f);
        b3d_voxel_render(v,    1, 0.0f);
        b3d_voxel_render_flat(NULL, 1, 1.0f);
        b3d_voxel_render_flat(v, 1, -1.0f);
        size_t bad = count_nonzero(px, 64, 64);
        printf("bad_px=%zu\n", bad);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "lit_range=1" in r.stdout
    assert "flat_range=1" in r.stdout
    assert "lit_center=0xff8800" in r.stdout
    assert "flat_center=0xff8800" in r.stdout
    assert "bad_px=0" in r.stdout


# ---------------------------------------------------------------------------
# Shared helper (mirrors _pixel_count_helper from test_b3d.py)
# ---------------------------------------------------------------------------


def _pixel_count_helper():
    return r"""
    static size_t count_nonzero(const uint32_t *pixels, int w, int h) {
        size_t n = 0;
        for (int i = 0; i < w * h; i++)
            if (pixels[i] != 0) n++;
        return n;
    }
    static size_t count_nonzero_region(const uint32_t *pixels, int w, int h,
                                       int x0, int y0, int x1, int y1) {
        size_t n = 0;
        for (int y = y0; y < y1; y++)
            for (int x = x0; x < x1; x++)
                if (x >= 0 && x < w && y >= 0 && y < h && pixels[y*w+x] != 0) n++;
        return n;
    }
    """


# ---------------------------------------------------------------------------
# R1 — Rasterizer produces plausible pixel count for a mid-size triangle
# ---------------------------------------------------------------------------


def test_R1_triangle_pixel_count_bounds(build_and_run):
    """Front-facing triangle at z=0 viewed by camera at z=-3 with fov=65.
    Reference paints ~195 pixels; a wholesale-broken rasterizer will fall
    outside the [100, 400] range."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        /* Approximately covers a 40x40 bbox in a 64x64 frame. Half-triangle
         * area ≈ 800 pixels. */
        b3d_tri_t t = {{
            {-0.6f, -0.5f, 0.0f},
            {0.0f,  0.7f, 0.0f},
            {0.6f, -0.5f, 0.0f}
        }};
        int drew = b3d_triangle(&t, 0xffffff) ? 1 : 0;
        size_t n = count_nonzero(px, 64, 64);
        int in_range = (n >= 100 && n <= 400) ? 1 : 0;
        printf("drew=%d n=%zu in_range=%d\n", drew, n, in_range);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "drew=1" in r.stdout
    assert "in_range=1" in r.stdout


# ---------------------------------------------------------------------------
# R2 — Four triangles at four corners each paint pixels in their own corner
# ---------------------------------------------------------------------------


def test_R2_corner_regions(build_and_run):
    """Renders a distinctly-colored triangle near each of the 4 screen corners
    and verifies each corner's OWN color lands in its quadrant (red top-left,
    green top-right, blue bottom-left, yellow bottom-right). Checking the
    specific color per quadrant — not mere occupancy — discriminates an
    axis-flip / screen-projection bug that maps the four triangles to four
    different quadrants (which a bare non-empty check would still pass)."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>

    static int color_in_region(const uint32_t *p, int w, int x0, int y0,
                               int x1, int y1, uint32_t col) {
        for (int y = y0; y < y1; y++)
            for (int x = x0; x < x1; x++)
                if ((p[y*w + x] & 0xffffffu) == col) return 1;
        return 0;
    }
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -1, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        /* Small triangle centered at each corner in world space. Camera at
         * (0,0,-1) with fov=90 sees x,y in [-1, 1] as the whole frame. */
        /* Apex-up triangles are CCW when ordered (bottom-left, apex, bottom-right). */
        b3d_tri_t tl = {{ {-0.9f, 0.7f, 0.0f}, {-0.6f, 0.9f, 0.0f}, {-0.3f, 0.7f, 0.0f} }};
        b3d_tri_t tr = {{ {0.3f, 0.7f, 0.0f}, {0.6f, 0.9f, 0.0f}, {0.9f, 0.7f, 0.0f} }};
        /* Apex-down triangles need reversed order (bottom-left, bottom-right, apex)
         * to stay CCW as seen by the camera. */
        b3d_tri_t bl = {{ {-0.9f, -0.7f, 0.0f}, {-0.3f, -0.7f, 0.0f}, {-0.6f, -0.9f, 0.0f} }};
        b3d_tri_t br = {{ {0.3f, -0.7f, 0.0f}, {0.9f, -0.7f, 0.0f}, {0.6f, -0.9f, 0.0f} }};

        /* CCW-wound as seen from camera at z=-1 looking at z=0. */
        b3d_triangle(&tl, 0xff0000);
        b3d_triangle(&tr, 0x00ff00);
        b3d_triangle(&bl, 0x0000ff);
        b3d_triangle(&br, 0xffff00);

        /* Screen top = small y (screen y flipped), so "world +Y" corners appear
         * at low screen-y values. Assert each corner's own color lands there. */
        int tl_red    = color_in_region(px, 64,  0,  0, 32, 32, 0xff0000);
        int tr_green  = color_in_region(px, 64, 32,  0, 64, 32, 0x00ff00);
        int bl_blue   = color_in_region(px, 64,  0, 32, 32, 64, 0x0000ff);
        int br_yellow = color_in_region(px, 64, 32, 32, 64, 64, 0xffff00);
        printf("tl_red=%d tr_green=%d bl_blue=%d br_yellow=%d\n",
               tl_red, tr_green, bl_blue, br_yellow);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "tl_red=1 tr_green=1 bl_blue=1 br_yellow=1" in r.stdout


# ---------------------------------------------------------------------------
# R3 — Triangle entirely off-screen returns cleanly and paints no pixels
# ---------------------------------------------------------------------------


def test_R3_triangle_fully_off_screen_top(build_and_run):
    """Front-facing triangle entirely above the visible frustum in NDC (all
    y-projected far above +1 in NDC). Must not crash; must paint zero pixels;
    return value is unconstrained (some impls project + screen-cull; others
    return false)."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 60.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        /* Triangle far above the frame (all y > +5 in world space, close to
         * camera so NDC y >> 1). */
        b3d_tri_t t = {{
            {-1.0f, 5.0f, 0.0f},
            {0.0f,  7.0f, 0.0f},
            {1.0f,  5.0f, 0.0f}
        }};
        b3d_triangle(&t, 0xffffff);
        size_t n = count_nonzero(px, 64, 64);
        printf("off_screen_px=%zu\n", n);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "off_screen_px=0" in r.stdout


# ---------------------------------------------------------------------------
# R4-R5 — Triangles straddling the screen edges (y-clamp and x-clamp)
# ---------------------------------------------------------------------------


def test_R4_triangle_straddles_top_bottom_edges(build_and_run):
    """The two vertical (y-clamp) straddle cases in one test: a triangle whose
    apex runs off the TOP edge and one whose apex runs off the BOTTOM edge.
    Each must paint into the visible frame on the straddled side AND leave the
    opposite half empty — the off-screen portion is clipped to the frame, not
    wrapped or flooded across it. Merges the former one-per-edge tests, which
    rewarded the single 'clamp a partially off-screen triangle' behavior more
    than once."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -1, 0, 0, 0});

        /* Apex above the top edge, base inside (screen y flipped, so the
         * painted region is the top half only). */
        b3d_clear();
        b3d_reset();
        b3d_triangle(&(b3d_tri_t){{
            {-0.5f, 0.3f, 0.0f}, {0.0f, 1.5f, 0.0f}, {0.5f, 0.3f, 0.0f}
        }}, 0xffffff);
        size_t top_total   = count_nonzero(px, 64, 64);
        size_t top_in_top  = count_nonzero_region(px, 64, 64, 0,  0, 64, 32);
        size_t top_in_bot  = count_nonzero_region(px, 64, 64, 0, 32, 64, 64);

        /* Apex below the bottom edge, base inside — painted region is the
         * bottom half only. */
        b3d_clear();
        b3d_reset();
        b3d_triangle(&(b3d_tri_t){{
            {-0.5f, -0.3f, 0.0f}, {0.5f, -0.3f, 0.0f}, {0.0f, -1.5f, 0.0f}
        }}, 0xffffff);
        size_t bot_total   = count_nonzero(px, 64, 64);
        size_t bot_in_bot  = count_nonzero_region(px, 64, 64, 0, 32, 64, 64);
        size_t bot_in_top  = count_nonzero_region(px, 64, 64, 0,  0, 64, 32);

        printf("top total=%d in_top=%d bot_empty=%d | bot total=%d in_bot=%d top_empty=%d\n",
               top_total > 0, top_in_top > 0, top_in_bot == 0,
               bot_total > 0, bot_in_bot > 0, bot_in_top == 0);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert (
        "top total=1 in_top=1 bot_empty=1 | bot total=1 in_bot=1 top_empty=1"
        in r.stdout
    )


def test_R5_triangle_straddles_left_right_edges(build_and_run):
    """The two horizontal (x-clamp) straddle cases in one test: a triangle
    whose apex runs off the LEFT edge and one whose apex runs off the RIGHT
    edge. Each must paint into the visible frame on the straddled side AND
    leave the far opposite quarter empty — the off-screen portion is clipped
    to the frame, not wrapped or flooded across it."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -1, 0, 0, 0});

        /* Apex off the left edge, base to the right; painted region hugs the
         * left, so the far-right quarter stays empty. CCW as seen by camera. */
        b3d_clear();
        b3d_reset();
        b3d_triangle(&(b3d_tri_t){{
            {-1.5f, 0.0f, 0.0f}, {0.3f, 0.5f, 0.0f}, {0.3f, -0.5f, 0.0f}
        }}, 0xffffff);
        size_t left_total     = count_nonzero(px, 64, 64);
        size_t left_in_left   = count_nonzero_region(px, 64, 64,  0, 0, 32, 64);
        size_t left_far_right = count_nonzero_region(px, 64, 64, 48, 0, 64, 64);

        /* Apex off the right edge, base to the left; far-left quarter empty. */
        b3d_clear();
        b3d_reset();
        b3d_triangle(&(b3d_tri_t){{
            {-0.3f, 0.5f, 0.0f}, {1.5f, 0.0f, 0.0f}, {-0.3f, -0.5f, 0.0f}
        }}, 0xffffff);
        size_t right_total    = count_nonzero(px, 64, 64);
        size_t right_in_right = count_nonzero_region(px, 64, 64, 32, 0, 64, 64);
        size_t right_far_left = count_nonzero_region(px, 64, 64,  0, 0, 16, 64);

        printf("left total=%d in_left=%d farright_empty=%d | right total=%d in_right=%d farleft_empty=%d\n",
               left_total > 0, left_in_left > 0, left_far_right == 0,
               right_total > 0, right_in_right > 0, right_far_left == 0);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert (
        "left total=1 in_left=1 farright_empty=1 | right total=1 in_right=1 farleft_empty=1"
        in r.stdout
    )


# ---------------------------------------------------------------------------
# R8 — Single-pixel triangle
# ---------------------------------------------------------------------------


def test_R8_single_pixel_triangle(build_and_run):
    """Extremely small front-facing triangle. Should paint 1-6 pixels near
    screen center. Discriminates rasterizers that over-fill or drop
    sub-pixel triangles."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 60.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -1, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        b3d_tri_t t = {{
            {-0.02f, -0.02f, 0.0f},
            {0.0f,   0.02f, 0.0f},
            {0.02f, -0.02f, 0.0f}
        }};
        int drew = b3d_triangle(&t, 0xff8800) ? 1 : 0;
        size_t n = count_nonzero(px, 64, 64);
        /* Somewhere between 0 and 10 pixels; specifically, at least 1 if the
         * rasterizer honors sub-pixel triangles at all. */
        printf("drew=%d n=%zu tiny_ok=%d\n", drew, n, (n >= 1 && n <= 10));
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "drew=1 " in r.stdout
    assert "tiny_ok=1" in r.stdout


# ---------------------------------------------------------------------------
# R9 — Huge triangle covers entire framebuffer
# ---------------------------------------------------------------------------


def test_R9_triangle_covers_full_frame(build_and_run):
    """Front-facing triangle large enough to cover every pixel on a 32x32
    frame. Almost all pixels should be the triangle color."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[32*32];
        static b3d_depth_t dp[32*32];
        if (!b3d_init(px, dp, 32, 32, 60.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -1, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        /* Very wide triangle in world space so its projected bbox exceeds
         * the frame. CCW as seen from camera. */
        b3d_tri_t t = {{
            {-10.0f, -10.0f, 0.0f},
            {0.0f,   30.0f, 0.0f},
            {10.0f, -10.0f, 0.0f}
        }};
        int drew = b3d_triangle(&t, 0xffcc00) ? 1 : 0;
        size_t n = count_nonzero(px, 32, 32);
        /* At least 80% coverage — allow slop at edges for fixed-point rounding */
        int covered = (n >= (size_t)(32*32*0.8)) ? 1 : 0;
        printf("drew=%d n=%zu covered=%d\n", drew, n, covered);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "drew=1 " in r.stdout
    assert "covered=1" in r.stdout


# ---------------------------------------------------------------------------
# R10 — Three triangles at different depths — middle wins at overlap
# ---------------------------------------------------------------------------


def test_R10_depth_three_layers_middle_wins_at_edge(build_and_run):
    """Three concentric apex-up triangles at world z = 1.5 / 0.5 / -0.5
    (far/mid/near with the camera at z=-3). At the center the nearest (blue)
    triangle must win, and it must keep winning when the triangles are painted
    in the reverse order (near first, far last) — a painter's-algorithm
    implementation with no depth buffer would instead show the last-drawn far
    color. A two-layer mid-then-far frame confirms the middle triangle wins
    over the farther one at the center where they overlap."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_reset();

        b3d_tri_t far_tri = {{           /* largest, farthest */
            {-1.0f, -1.0f, 1.5f},
            {0.0f,   1.5f, 1.5f},
            {1.0f,  -1.0f, 1.5f}
        }};
        b3d_tri_t mid_tri = {{           /* medium depth */
            {-0.6f, -0.6f, 0.5f},
            {0.0f,   0.9f, 0.5f},
            {0.6f,  -0.6f, 0.5f}
        }};
        b3d_tri_t near_tri = {{          /* smallest, nearest */
            {-0.25f, -0.25f, -0.5f},
            {0.0f,    0.35f, -0.5f},
            {0.25f,  -0.25f, -0.5f}
        }};

        /* Forward paint order far -> mid -> near: near (blue) wins at center. */
        b3d_clear();
        b3d_triangle(&far_tri,  0xff0000);
        b3d_triangle(&mid_tri,  0x00ff00);
        b3d_triangle(&near_tri, 0x0000ff);
        uint32_t fwd_center = px[64/2 * 64 + 64/2] & 0xffffffu;

        /* Reverse paint order near -> mid -> far (far drawn LAST). The depth
           test must still keep the nearest (blue) fragment; a no-depth-buffer
           painter's impl would show the last-drawn far (red) here. */
        b3d_clear();
        b3d_triangle(&near_tri, 0x0000ff);
        b3d_triangle(&mid_tri,  0x00ff00);
        b3d_triangle(&far_tri,  0xff0000);
        uint32_t rev_center = px[64/2 * 64 + 64/2] & 0xffffffu;

        /* Two layers, mid then far (far LAST): the middle (green) triangle is
           nearer than far at the center, so depth testing keeps green. */
        b3d_clear();
        b3d_triangle(&mid_tri, 0x00ff00);
        b3d_triangle(&far_tri, 0xff0000);
        uint32_t midfar_center = px[64/2 * 64 + 64/2] & 0xffffffu;

        printf("fwd_center=0x%06x rev_center=0x%06x midfar_center=0x%06x\n",
               (unsigned)fwd_center, (unsigned)rev_center,
               (unsigned)midfar_center);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "fwd_center=0x0000ff" in r.stdout
    assert "rev_center=0x0000ff" in r.stdout
    assert "midfar_center=0x00ff00" in r.stdout


# ---------------------------------------------------------------------------
# R12 — Lighting with ambient=0 and perpendicular light → black
# ---------------------------------------------------------------------------


def test_R12_lighting_zero_ambient_perpendicular_black(build_and_run):
    """With ambient=0 and light perpendicular to normal, intensity=0 → any
    pixel painted is exactly 0x000000 (which means the framebuffer, cleared
    to 0, is indistinguishable — so also verify the triangle DID rasterize
    somewhere by tracking depth-buffer change). Assert the center pixel is
    0."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -2, 0, 0, 0});
        b3d_reset();
        b3d_set_ambient(0.0f);
        b3d_set_light_direction(1.0f, 0.0f, 0.0f);  /* perp to +Z normal */

        b3d_clear();
        int drew = b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, -1.0f, 0xffffff) ? 1 : 0;
        uint32_t center = px[64/2 * 64 + 64/2] & 0xffffffu;
        printf("drew=%d center=0x%06x\n", drew, (unsigned)center);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "drew=1" in r.stdout
    assert "center=0x000000" in r.stdout


# ---------------------------------------------------------------------------
# R13 — Lighting at 60° normal-light gives half intensity
# ---------------------------------------------------------------------------


def test_R13_lighting_60_degree_half_intensity(build_and_run):
    """ambient=0, normal (0,0,-1), light direction at 60° from normal
    (light = (sin60,0,-cos60) ≈ (0.866,0,-0.5)). intensity = 0 + 1 *
    |dot((0,0,-1),(0.866,0,-0.5))| = 0.5. Base=0xffffff → center pixel
    ≈ 0x7f7f7f (127 = 0.5*255)."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -2, 0, 0, 0});
        b3d_reset();
        b3d_set_ambient(0.0f);
        b3d_set_light_direction(0.866025f, 0.0f, -0.5f);

        b3d_clear();
        b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, -1.0f, 0xffffff);
        uint32_t c = px[64/2 * 64 + 64/2] & 0xffffffu;
        unsigned r = (c >> 16) & 0xff, g = (c >> 8) & 0xff, b = c & 0xff;
        /* Expect ~127 per channel — allow generous tolerance for LUT trig */
        int ok = (r >= 110 && r <= 145) && (g >= 110 && g <= 145) && (b >= 110 && b <= 145);
        printf("center=0x%06x r=%u g=%u b=%u ok=%d\n",
               (unsigned)c, r, g, b, ok);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "ok=1" in r.stdout


# ---------------------------------------------------------------------------
# R14 — Non-unit normal is normalized internally
# ---------------------------------------------------------------------------


def test_R14_lighting_non_unit_normal_normalized(build_and_run):
    """Two lit triangles: same geometry, same light, ambient=0.2. One passed
    a unit normal (0,0,-1), the other a scaled non-unit normal (0,0,-3).
    Center-pixel colors should be identical since impl normalizes."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -2, 0, 0, 0});
        b3d_reset();
        b3d_set_ambient(0.2f);
        b3d_set_light_direction(0.0f, 0.0f, 1.0f);

        b3d_clear();
        b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, -1.0f, 0xffffff);
        uint32_t unit_c = px[64/2 * 64 + 64/2] & 0xffffffu;

        b3d_clear();
        b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, -3.0f, 0xffffff);
        uint32_t nonunit_c = px[64/2 * 64 + 64/2] & 0xffffffu;

        int match = ((int)(unit_c & 0xff) - (int)(nonunit_c & 0xff) < 4 &&
                     (int)(unit_c & 0xff) - (int)(nonunit_c & 0xff) > -4);
        printf("unit=0x%06x nonunit=0x%06x match=%d\n",
               (unsigned)unit_c, (unsigned)nonunit_c, match);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "match=1" in r.stdout


# ---------------------------------------------------------------------------
# R15 — Two-sided lighting: opposite-facing normal gives same intensity
# ---------------------------------------------------------------------------


def test_R15_lighting_opposite_normal_two_sided(build_and_run):
    """Instruction: `intensity = ambient + (1-ambient) * |dot(N, L)|`. Normal
    (0,0,+1) with light (0,0,+1) should give the same intensity as normal
    (0,0,-1) with same light — |dot| is symmetric."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -2, 0, 0, 0});
        b3d_reset();
        b3d_set_ambient(0.2f);
        b3d_set_light_direction(0.0f, 0.0f, 1.0f);

        b3d_clear();
        b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, -1.0f, 0xffffff);
        uint32_t neg_c = px[64/2 * 64 + 64/2] & 0xffffffu;

        b3d_clear();
        b3d_triangle_lit(
            &(b3d_tri_t){{{-0.5f,-0.5f,0}, {0.0f,0.5f,0}, {0.5f,-0.5f,0}}},
            0.0f, 0.0f, 1.0f, 0xffffff);
        uint32_t pos_c = px[64/2 * 64 + 64/2] & 0xffffffu;

        int match = ((int)(neg_c & 0xff) - (int)(pos_c & 0xff) < 4 &&
                     (int)(neg_c & 0xff) - (int)(pos_c & 0xff) > -4);
        printf("neg=0x%06x pos=0x%06x match=%d\n",
               (unsigned)neg_c, (unsigned)pos_c, match);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "match=1" in r.stdout


# ---------------------------------------------------------------------------
# R16 — Matrix stack + rendering interaction: push/translate/render/pop/render
# ---------------------------------------------------------------------------


def test_R16_matrix_stack_render_isolation(build_and_run):
    """Isolate push/translate/pop across three separate frames. The centered
    triangle projects around screen x=28-33, so a positive world-x translate is
    the only way to paint the far-right region (x>=36). Frame 1 (origin) leaves
    the far-right empty; frame 2 (push + translate +1) paints it; frame 3 (pop,
    back at origin) leaves it empty again. A no-op translate fails frame 2 and a
    no-op pop repaints the far-right in frame 3."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_reset();

        b3d_tri_t t = {{
            {-0.3f, -0.3f, 0.0f},
            {0.0f,  0.3f, 0.0f},
            {0.3f, -0.3f, 0.0f}
        }};

        /* Frame 1: render at the origin. The far-right region (x>=36) is
           reachable only via a positive world-x translate, so it is empty. */
        b3d_clear();
        b3d_triangle(&t, 0xff0000);
        size_t origin_left  = count_nonzero_region(px, 64, 64,  0, 0, 32, 64);
        size_t origin_right = count_nonzero_region(px, 64, 64, 36, 0, 64, 64);

        /* Frame 2: push, translate +1 in world x, render. The triangle now
           projects into the far-right region. A no-op push/translate leaves
           it empty. */
        b3d_push_matrix();
        b3d_translate(1.0f, 0.0f, 0.0f);
        b3d_clear();
        b3d_triangle(&t, 0x00ff00);
        size_t pushed_right = count_nonzero_region(px, 64, 64, 36, 0, 64, 64);

        /* Frame 3: pop restores the pre-push (origin) matrix, so this render is
           back at the origin and the far-right region is empty again. A no-op
           pop keeps the +1 translation and repaints the far-right. */
        b3d_pop_matrix();
        b3d_clear();
        b3d_triangle(&t, 0x0000ff);
        size_t popped_right = count_nonzero_region(px, 64, 64, 36, 0, 64, 64);

        printf("origin_left=%d origin_right=%d pushed_right=%d popped_right=%d\n",
               origin_left > 0, origin_right == 0, pushed_right > 0,
               popped_right == 0);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "origin_left=1 origin_right=1 pushed_right=1 popped_right=1" in r.stdout


# ---------------------------------------------------------------------------
# R17 — b3d_to_screen matches actual rasterized pixel
# ---------------------------------------------------------------------------


def test_R17_to_screen_matches_rasterized_pixel(build_and_run):
    """Project a world point via b3d_to_screen; then render a small triangle
    centered on that same world point. The returned screen coord should be
    inside the painted region."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -2, 0, 0, 0});
        b3d_clear();
        b3d_reset();

        /* Project world point (0.5, 0.3, 0) → (sx, sy) */
        int sx = -1, sy = -1;
        int ok = b3d_to_screen(0.5f, 0.3f, 0.0f, &sx, &sy) ? 1 : 0;
        int in_bounds = (sx >= 0 && sx < 64 && sy >= 0 && sy < 64) ? 1 : 0;

        /* Render a small triangle centered on that world point */
        b3d_tri_t t = {{
            {0.5f - 0.15f, 0.3f - 0.15f, 0.0f},
            {0.5f,         0.3f + 0.15f, 0.0f},
            {0.5f + 0.15f, 0.3f - 0.15f, 0.0f}
        }};
        b3d_triangle(&t, 0xffaa00);

        /* The projected pixel should be painted (allow 1-pixel jitter) */
        int hit = 0;
        for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
                int x = sx + dx, y = sy + dy;
                if (x < 0 || x >= 64 || y < 0 || y >= 64) continue;
                if (px[y * 64 + x] != 0) hit = 1;
            }
        }
        printf("proj_ok=%d in_bounds=%d hit=%d\n", ok, in_bounds, hit);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "proj_ok=1 in_bounds=1 hit=1" in r.stdout


# ---------------------------------------------------------------------------
# R18 — Multi-voxel array: per-voxel color and spatial placement
# ---------------------------------------------------------------------------


def test_R18_voxel_render_flat_multi_voxel_placement(build_and_run):
    """Two voxels at different world x with different colors render to
    different screen regions, each keeping its own (flat/unlit) color: the
    left voxel's color appears only in the left half and the right voxel's only
    in the right half. Exercises per-voxel color and spatial placement of a
    voxel array — a distinct behavior beyond the single-voxel footprint and
    base-color-at-center already checked by test_voxel_render_paints_pixels."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    #include <b3d-voxel.h>

    static int color_in_region(const uint32_t *p, int w, int x0, int y0,
                               int x1, int y1, uint32_t col) {
        for (int y = y0; y < y1; y++)
            for (int x = x0; x < x1; x++)
                if ((p[y*w + x] & 0xffffffu) == col) return 1;
        return 0;
    }
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -6, 0, 0, 0});
        b3d_reset();

        /* Green voxel to the left (world -x), orange to the right (+x). */
        b3d_voxel_t v[2] = {
            {{-1.2f, 0.0f, 0.0f}, 0x00ff00},
            {{ 1.2f, 0.0f, 0.0f}, 0xff8800},
        };
        b3d_clear();
        b3d_voxel_render_flat(v, 2, 1.0f);

        int left_green   = color_in_region(px, 64,  0, 0, 32, 64, 0x00ff00);
        int left_orange  = color_in_region(px, 64,  0, 0, 32, 64, 0xff8800);
        int right_green  = color_in_region(px, 64, 32, 0, 64, 64, 0x00ff00);
        int right_orange = color_in_region(px, 64, 32, 0, 64, 64, 0xff8800);
        printf("left_green=%d left_orange=%d right_green=%d right_orange=%d\n",
               left_green, left_orange, right_green, right_orange);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "left_green=1 left_orange=0 right_green=0 right_orange=1" in r.stdout


# ---------------------------------------------------------------------------
# R20 — Voxel lit with ambient<1 gives strictly-darker pixels than flat
# ---------------------------------------------------------------------------


def test_R20_voxel_render_lit_darker_than_flat(build_and_run):
    """b3d_voxel_render uses lit (ambient=0.2, light=+Z), b3d_voxel_render_flat
    uses base color directly. For a face oriented such that |dot(N,L)| < 1,
    lit intensity < 1 → lit pixel darker than flat pixel."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    #include <b3d-voxel.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_reset();
        b3d_set_ambient(0.2f);
        b3d_set_light_direction(1.0f, 0.0f, 0.0f);  /* light along +X */

        b3d_voxel_t v[1] = {{{0.0f, 0.0f, 0.0f}, 0xffffff}};

        b3d_clear();
        b3d_voxel_render_flat(v, 1, 1.0f);
        uint32_t flat_c = px[64/2 * 64 + 64/2] & 0xffffffu;

        b3d_clear();
        b3d_voxel_render(v, 1, 1.0f);
        uint32_t lit_c = px[64/2 * 64 + 64/2] & 0xffffffu;

        unsigned flat_r = (flat_c >> 16) & 0xff;
        unsigned lit_r  = (lit_c  >> 16) & 0xff;
        /* Center is the front face (-Z normal). Light is +X. |dot| = 0.
         * intensity = 0.2 + 0.8*0 = 0.2. lit_r ≈ 51, flat_r == 255. */
        int lit_darker = (lit_r < flat_r - 10) ? 1 : 0;
        printf("flat=0x%06x lit=0x%06x lit_darker=%d\n",
               (unsigned)flat_c, (unsigned)lit_c, lit_darker);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "lit_darker=1" in r.stdout


# ---------------------------------------------------------------------------
# R21 — Render after reset: state actually cleared
# ---------------------------------------------------------------------------


def test_R21_render_after_reset_uses_new_matrix(build_and_run):
    """Apply a translate, render (pixels in region A), reset (matrix back to
    identity), render (pixels in region B). A and B should be in different
    regions of the frame."""
    driver = (
        r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_clear();

        b3d_tri_t t = {{
            {-0.25f, -0.25f, 0.0f},
            {0.0f,   0.25f, 0.0f},
            {0.25f, -0.25f, 0.0f}
        }};

        /* Shifted right */
        b3d_reset();
        b3d_translate(1.0f, 0.0f, 0.0f);
        b3d_triangle(&t, 0xff0000);
        size_t right_after_first = count_nonzero_region(px, 64, 64, 32, 0, 64, 64);
        size_t left_after_first  = count_nonzero_region(px, 64, 64,  0, 0, 32, 64);

        /* Now at origin */
        b3d_reset();
        b3d_triangle(&t, 0x0000ff);
        size_t right_after_second = count_nonzero_region(px, 64, 64, 32, 0, 64, 64);
        size_t left_after_second  = count_nonzero_region(px, 64, 64,  0, 0, 32, 64);

        /* First render should have been in right; after reset+centered
         * render the left region should also have pixels. */
        printf("first_right_only=%d second_covers_both=%d\n",
               (right_after_first > 0 && left_after_first == 0) ? 1 : 0,
               (right_after_second > 0 && left_after_second > 0) ? 1 : 0);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "first_right_only=1 second_covers_both=1" in r.stdout


# ---------------------------------------------------------------------------
# R22 — b3d_look_at reorients the view matrix toward the target
# ---------------------------------------------------------------------------


def test_R22_look_at_orients_toward_target(build_and_run):
    """From a camera at (2, 0, -3) with default orientation (yaw=pitch=roll=0),
    the world origin projects OFF-CENTER (camera is looking at +Z, origin is
    2 units to the left of forward axis). After b3d_look_at(0, 0, 0), the
    view rotates so the origin projects TO the screen center. This proves
    look_at actually recomputes the view matrix — not just a no-op that
    keeps the stored yaw/pitch/roll."""
    driver = r"""
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){2.0f, 0.0f, -3.0f, 0, 0, 0});

        /* Baseline: origin should NOT be at screen center (camera is 2
         * units right of the target's line of sight). */
        int sx0, sy0;
        int in0 = b3d_to_screen(0.0f, 0.0f, 0.0f, &sx0, &sy0) ? 1 : 0;
        int off_center = (in0 && (sx0 < 20 || sx0 > 44)) ? 1 : 0;

        /* After look_at(origin), origin should project TO screen center. */
        b3d_look_at(0.0f, 0.0f, 0.0f);
        int sx1, sy1;
        int in1 = b3d_to_screen(0.0f, 0.0f, 0.0f, &sx1, &sy1) ? 1 : 0;
        int centered =
            (in1 && sx1 >= 28 && sx1 <= 36 && sy1 >= 28 && sy1 <= 36) ? 1 : 0;

        printf("in0=%d sx0=%d sy0=%d off_center=%d\n", in0, sx0, sy0, off_center);
        printf("in1=%d sx1=%d sy1=%d centered=%d\n", in1, sx1, sy1, centered);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "in0=1" in r.stdout
    assert "off_center=1" in r.stdout
    assert "in1=1" in r.stdout
    assert "centered=1" in r.stdout


# ---------------------------------------------------------------------------
# R23 — Rendering respects b3d_rotate_y: 90° rotation makes XY triangle
#       edge-on and it stops covering pixels
# ---------------------------------------------------------------------------


def test_R23_render_with_y_rotation(build_and_run):
    """Baseline: front-facing XY triangle paints > 100 pixels. Same triangle
    with b3d_rotate_y(pi/2) applied is rotated into the YZ plane — edge-on
    to the camera — and paints < 20 pixels (a thin sliver at most).
    Distinguishes an impl that stores the rotation matrix from one that
    silently ignores it during rendering."""
    driver = (
        r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});

        b3d_tri_t t = {{
            {-0.6f, -0.5f, 0.0f},
            {0.0f,  0.7f, 0.0f},
            {0.6f, -0.5f, 0.0f}
        }};

        /* No rotation: standard front-facing render. */
        b3d_reset();
        b3d_clear();
        b3d_triangle(&t, 0xffffff);
        size_t n_norot = count_nonzero(px, 64, 64);

        /* Rotate 90° around Y — triangle becomes edge-on. */
        b3d_reset();
        b3d_rotate_y(1.5707963f);  /* pi/2 */
        b3d_clear();
        b3d_triangle(&t, 0xffffff);
        size_t n_rot90 = count_nonzero(px, 64, 64);

        int norot_bounds  = (n_norot > 100) ? 1 : 0;
        int rot90_bounds  = (n_rot90 < 20)  ? 1 : 0;
        printf("n_norot=%zu norot_ok=%d n_rot90=%zu rot90_ok=%d\n",
               n_norot, norot_bounds, n_rot90, rot90_bounds);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "norot_ok=1" in r.stdout
    assert "rot90_ok=1" in r.stdout


# ---------------------------------------------------------------------------
# R24 — Lit intensity is invariant under model rotation (lighting in model
#       space — the "rotates with the object" clause)
# ---------------------------------------------------------------------------


def test_R24_lit_intensity_invariant_under_rotation(build_and_run):
    """Spec: 'Lighting is computed in model space, so the shading is fixed
    relative to the object and rotates with it.' Concretely: both the surface
    normal and the light direction are in model space, so dot(N, L) is
    invariant under any model-space rotation. Test: render a lit triangle
    with normal (0,0,-1) and light (0,0,1); ambient=0 so intensity = |dot|
    = 1.0, and full-white base gives max channel value 255 in the painted
    region. Applying b3d_rotate_y(pi/6) moves the triangle on screen but
    the peak painted brightness must remain 255. An impl that computes
    lighting in world space (post-model-transform) would rotate the effective
    normal and produce a different intensity."""
    driver = (
        r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    static unsigned max_red(const uint32_t *p, int w, int h) {
        unsigned m = 0;
        for (int i = 0; i < w*h; i++) {
            unsigned r = (p[i] >> 16) & 0xff;
            if (r > m) m = r;
        }
        return m;
    }
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -3, 0, 0, 0});
        b3d_set_ambient(0.0f);
        b3d_set_light_direction(0.0f, 0.0f, 1.0f);

        b3d_tri_t t = {{
            {-0.8f, -0.7f, 0.0f},
            {0.0f,   0.8f, 0.0f},
            {0.8f,  -0.7f, 0.0f}
        }};

        /* Rotation 0. */
        b3d_reset();
        b3d_clear();
        b3d_triangle_lit(&t, 0.0f, 0.0f, -1.0f, 0xffffff);
        unsigned m0 = max_red(px, 64, 64);
        size_t n0 = count_nonzero(px, 64, 64);

        /* Rotate 30° around Y — triangle moves on screen but stays
         * visible. Same normal, same light — dot(N,L) is unchanged. */
        b3d_reset();
        b3d_rotate_y(0.5235988f);  /* pi/6 */
        b3d_clear();
        b3d_triangle_lit(&t, 0.0f, 0.0f, -1.0f, 0xffffff);
        unsigned m1 = max_red(px, 64, 64);
        size_t n1 = count_nonzero(px, 64, 64);

        int both_visible = (n0 > 50 && n1 > 50) ? 1 : 0;
        int m0_full = (m0 >= 250) ? 1 : 0;
        int m1_full = (m1 >= 250) ? 1 : 0;
        printf("n0=%zu n1=%zu m0=%u m1=%u both_visible=%d full=%d,%d\n",
               n0, n1, m0, m1, both_visible, m0_full, m1_full);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "both_visible=1" in r.stdout
    assert "full=1,1" in r.stdout
# ---------------------------------------------------------------------------
# Shared helpers (mirror those in test_b3d.py)
# ---------------------------------------------------------------------------


def _pixel_count_helper():
    return r"""
    static size_t count_nonzero(const uint32_t *pixels, int w, int h) {
        size_t n = 0;
        for (int i = 0; i < w * h; i++)
            if (pixels[i] != 0) n++;
        return n;
    }
    static size_t count_nonzero_region(const uint32_t *pixels, int w, int h,
                                       int x0, int y0, int x1, int y1) {
        size_t n = 0;
        for (int y = y0; y < y1; y++)
            for (int x = x0; x < x1; x++)
                if (x >= 0 && x < w && y >= 0 && y < h && pixels[y*w+x] != 0) n++;
        return n;
    }
    static unsigned max_channel(const uint32_t *p, int w, int h, int shift) {
        unsigned m = 0;
        for (int i = 0; i < w*h; i++) {
            unsigned v = (p[i] >> shift) & 0xff;
            if (v > m) m = v;
        }
        return m;
    }
    """


# ---------------------------------------------------------------------------
# GROUP A: Model-space lighting invariance (multiple angles / code paths)
# ---------------------------------------------------------------------------


def test_R27_voxel_render_lit_intensity_invariant_under_rotation(build_and_run):
    """Model-space lighting through the b3d_voxel_render code path. A voxel
    rendered with the light aligned to a face normal should paint that face
    at max intensity (255) regardless of any model-space rotation applied
    before rendering. World-space lighting impls rotate the effective normal
    and produce sub-max intensity."""
    driver = (
        r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    #include <b3d-voxel.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 65.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -4, 0, 0, 0});
        b3d_set_ambient(0.0f);
        b3d_set_light_direction(0, 0, 1);

        b3d_voxel_t v[1] = {{{0.0f, 0.0f, 0.0f}, 0xffffff}};

        /* Reference: no rotation — front face fully lit. */
        b3d_reset();
        b3d_clear();
        b3d_voxel_render(v, 1, 1.0f);
        unsigned m0 = max_channel(px, 64, 64, 16);

        /* With rotation — front face is still normal (0,0,-1) in MODEL space.
         * Model-space lighting: peak stays at 255.
         * World-space lighting: peak drops (rotated effective normal). */
        b3d_reset();
        b3d_rotate_y(0.5f);
        b3d_clear();
        b3d_voxel_render(v, 1, 1.0f);
        unsigned m1 = max_channel(px, 64, 64, 16);

        printf("m0=%u m1=%u no_rot_full=%d with_rot_full=%d\n",
               m0, m1, (m0 >= 250), (m1 >= 250));
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "no_rot_full=1 with_rot_full=1" in r.stdout


# ---------------------------------------------------------------------------
# GROUP B: Rotation matrix composition and sign convention
# ---------------------------------------------------------------------------


def test_R29_rotation_composition_matrix_cells(build_and_run):
    """Post-multiply composition: rotate_x(a) then rotate_y(b) produces
    v' = v * Rx * Ry. Reference DSL has:
      Rx = [[1,0,0,0], [0,cos,sin,0], [0,-sin,cos,0], [0,0,0,1]]
      Ry = [[cos,0,sin,0], [0,1,0,0], [-sin,0,cos,0], [0,0,0,1]]
    Rx * Ry row 1 = [-sin_a*sin_b, cos_a, sin_a*cos_b, 0].
    Assert specific cell values. Catches impls with transposed rotation
    matrices (they compose the opposite way and produce wrong cell values)."""
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        if (!b3d_init(px, dp, 16, 16, 60.0f)) return 1;

        float m[16];
        b3d_reset();
        b3d_rotate_x(0.3f);
        b3d_rotate_y(0.5f);
        b3d_get_model_matrix(m);

        /* Expected row 0 = row 0 of Ry (since Rx row 0 is [1,0,0,0]):
         * [cos(0.5), 0, sin(0.5), 0] = [0.8776, 0, 0.4794, 0]. */
        int r0_ok = fabsf(m[0] - cosf(0.5f)) < 1e-3f &&
                    fabsf(m[1])              < 1e-3f &&
                    fabsf(m[2] - sinf(0.5f)) < 1e-3f;

        /* Expected row 1 = [-sin(0.3)*sin(0.5), cos(0.3), sin(0.3)*cos(0.5), 0]
         *                = [-0.1417, 0.9553, 0.2592, 0]. */
        int r1_ok = fabsf(m[4] - (-sinf(0.3f)*sinf(0.5f))) < 1e-3f &&
                    fabsf(m[5] - cosf(0.3f))               < 1e-3f &&
                    fabsf(m[6] - (sinf(0.3f)*cosf(0.5f)))  < 1e-3f;

        printf("r0=[%.4f %.4f %.4f] r1=[%.4f %.4f %.4f] r0_ok=%d r1_ok=%d\n",
               (double)m[0], (double)m[1], (double)m[2],
               (double)m[4], (double)m[5], (double)m[6],
               r0_ok, r1_ok);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "r0_ok=1 r1_ok=1" in r.stdout


def test_R30_translate_then_rotate_matrix_cells(build_and_run):
    """Post-multiply: translate(1,2,3) then rotate_z(pi/4).
    T * Rz row 3 = [1,2,3,1] * Rz = [cos-2*sin, sin+2*cos, 3, 1]
                                  = [0.7071 - 1.4142, 0.7071 + 1.4142, 3, 1]
                                  = [-0.7071, 2.1213, 3, 1].
    Also asserts row 0 = [cos, sin, 0, 0] = [0.7071, 0.7071, 0, 0]."""
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        if (!b3d_init(px, dp, 16, 16, 60.0f)) return 1;

        float m[16];
        b3d_reset();
        b3d_translate(1.0f, 2.0f, 3.0f);
        b3d_rotate_z(0.7853982f);  /* pi/4 */
        b3d_get_model_matrix(m);

        /* Row 0: [cos(pi/4), sin(pi/4), 0, 0] = [0.7071, 0.7071, 0, 0] */
        int r0_ok = fabsf(m[0] - 0.7071f) < 1e-3f &&
                    fabsf(m[1] - 0.7071f) < 1e-3f;

        /* Translation row: [-0.7071, 2.1213, 3, 1] */
        int tr_ok = fabsf(m[12] - (-0.7071f)) < 1e-3f &&
                    fabsf(m[13] -  2.1213f)   < 1e-3f &&
                    fabsf(m[14] -  3.0f)      < 1e-3f;

        printf("r0=[%.4f %.4f] tr=[%.4f %.4f %.4f] r0_ok=%d tr_ok=%d\n",
               (double)m[0], (double)m[1],
               (double)m[12], (double)m[13], (double)m[14],
               r0_ok, tr_ok);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "r0_ok=1 tr_ok=1" in r.stdout


# ---------------------------------------------------------------------------
# GROUP C: Rendering with rotation — visual consistency
# ---------------------------------------------------------------------------


def test_R31_rotate_z_shifts_rendered_triangle_ccw(build_and_run):
    """A small triangle at the top of the screen, rotated by pi/2 (90°)
    around Z should end up on the LEFT of the screen (CCW rotation for
    positive angle in right-handed +Z-forward coords). Discriminates impls
    that rotate in the OPPOSITE direction (transposed rotation matrix)."""
    driver = (
        r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    """
        + _pixel_count_helper()
        + r"""
    int main(void) {
        static uint32_t px[64*64];
        static b3d_depth_t dp[64*64];
        if (!b3d_init(px, dp, 64, 64, 90.0f)) return 1;
        b3d_set_camera(&(b3d_camera_t){0, 0, -1, 0, 0, 0});
        b3d_clear();

        /* Small triangle centered at world (0, 0.6, 0) — appears at TOP
         * of screen. */
        b3d_tri_t t = {{
            {-0.15f, 0.45f, 0.0f},
            {0.0f,   0.75f, 0.0f},
            {0.15f,  0.45f, 0.0f}
        }};

        /* No rotation: verify appears in top half. */
        b3d_reset();
        b3d_clear();
        b3d_triangle(&t, 0xff0000);
        size_t top = count_nonzero_region(px, 64, 64, 0, 0, 64, 32);
        size_t bot = count_nonzero_region(px, 64, 64, 0, 32, 64, 64);
        int at_top = (top > 0 && bot == 0) ? 1 : 0;

        /* Rotate pi/2 around Z: top triangle rotates CCW → left of screen. */
        b3d_reset();
        b3d_rotate_z(1.5707963f);
        b3d_clear();
        b3d_triangle(&t, 0xff0000);
        size_t left  = count_nonzero_region(px, 64, 64,  0, 0, 32, 64);
        size_t right = count_nonzero_region(px, 64, 64, 32, 0, 64, 64);
        int at_left  = (left  > 0 && right == 0) ? 1 : 0;
        int at_right = (right > 0 && left == 0)  ? 1 : 0;

        printf("no_rot top=%zu bot=%zu at_top=%d\n", top, bot, at_top);
        printf("rot90 left=%zu right=%zu at_left=%d at_right=%d\n",
               left, right, at_left, at_right);
        return 0;
    }
    """
    )
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "at_top=1" in r.stdout
    assert "at_left=1" in r.stdout


def test_R34_scale_then_rotate_x_composition_cells(build_and_run):
    """Post-multiply composition: scale(2, 3, 4) then rotate_x(0.3).
    M = S * Rx. With S = diag(2,3,4,1) and Rx per spec:
        Rx = [[1,0,0,0], [0,cos,sin,0], [0,-sin,cos,0], [0,0,0,1]]
    Row 1 of M = [0, 3*cos(0.3), 3*sin(0.3), 0] = [0, 2.866, 0.887, 0]
    Row 2 of M = [0, -4*sin(0.3), 4*cos(0.3), 0] = [0, -1.182, 3.821, 0]
    Impls with transposed rotation matrices get inverted signs on m[6]/m[9]."""
    driver = r"""
    #include <math.h>
    #include <stdio.h>
    #include <stdint.h>
    #include <b3d.h>
    int main(void) {
        static uint32_t px[16*16];
        static b3d_depth_t dp[16*16];
        if (!b3d_init(px, dp, 16, 16, 60.0f)) return 1;

        float m[16];
        b3d_reset();
        b3d_scale(2.0f, 3.0f, 4.0f);
        b3d_rotate_x(0.3f);
        b3d_get_model_matrix(m);

        /* Row 1: [0, 3*cos(0.3), 3*sin(0.3), 0] */
        int r1_ok = fabsf(m[4])                     < 1e-3f &&
                    fabsf(m[5] - 3.0f*cosf(0.3f))   < 1e-3f &&
                    fabsf(m[6] - 3.0f*sinf(0.3f))   < 1e-3f;

        /* Row 2: [0, -4*sin(0.3), 4*cos(0.3), 0] */
        int r2_ok = fabsf(m[8])                        < 1e-3f &&
                    fabsf(m[9]  - (-4.0f*sinf(0.3f)))  < 1e-3f &&
                    fabsf(m[10] - 4.0f*cosf(0.3f))     < 1e-3f;

        printf("r1=[%.4f %.4f %.4f] r2=[%.4f %.4f %.4f] r1_ok=%d r2_ok=%d\n",
               (double)m[4], (double)m[5], (double)m[6],
               (double)m[8], (double)m[9], (double)m[10],
               r1_ok, r2_ok);
        return 0;
    }
    """
    r = build_and_run(driver)
    assert r.returncode == 0
    assert "r1_ok=1 r2_ok=1" in r.stdout
