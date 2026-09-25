/*
 * Copyright 2012-2019 CNRS-UM LIRMM, CNRS-AIST JRL
 */

// includes
// std
#include <iostream>

// boost
#define BOOST_TEST_MODULE Jacobian
#include <boost/test/unit_test.hpp>

// SpaceVecAlg
#include <SpaceVecAlg/SpaceVecAlg>

// RBDyn
#include "RBDyn/Body.h"
#include "RBDyn/FA.h"
#include "RBDyn/FK.h"
#include "RBDyn/FV.h"
#include "RBDyn/Jacobian.h"
#include "RBDyn/Joint.h"
#include "RBDyn/MultiBody.h"
#include "RBDyn/MultiBodyConfig.h"
#include "RBDyn/MultiBodyGraph.h"
#include "RBDyn/NumericalIntegration.h"

// Arm
#include "SSSarm.h"
#include "XXXdualarm.h"
#include "XYZSarm.h"

namespace rbd
{

static constexpr double PI = 3.141592653589793238462643383279502884e+00;

} // namespace rbd

const double TOL = 0.0000001;

void checkMultiBodyEq(const rbd::MultiBody & mb,
                      std::vector<rbd::Body> bodies,
                      std::vector<rbd::Joint> joints,
                      std::vector<int> pred,
                      std::vector<int> succ,
                      std::vector<int> parent,
                      std::vector<sva::PTransformd> Xt)
{
  // bodies
  BOOST_CHECK_EQUAL_COLLECTIONS(mb.bodies().begin(), mb.bodies().end(), bodies.begin(), bodies.end());
  // joints
  BOOST_CHECK_EQUAL_COLLECTIONS(mb.joints().begin(), mb.joints().end(), joints.begin(), joints.end());
  // pred
  BOOST_CHECK_EQUAL_COLLECTIONS(mb.predecessors().begin(), mb.predecessors().end(), pred.begin(), pred.end());
  // succ
  BOOST_CHECK_EQUAL_COLLECTIONS(mb.successors().begin(), mb.successors().end(), succ.begin(), succ.end());
  // parent
  BOOST_CHECK_EQUAL_COLLECTIONS(mb.parents().begin(), mb.parents().end(), parent.begin(), parent.end());

  // Xt
  BOOST_CHECK_EQUAL_COLLECTIONS(mb.transforms().begin(), mb.transforms().end(), Xt.begin(), Xt.end());

  // nrBodies
  BOOST_CHECK_EQUAL(mb.nrBodies(), bodies.size());
  // nrJoints
  BOOST_CHECK_EQUAL(mb.nrJoints(), bodies.size());

  int params = 0, dof = 0;
  for(std::size_t i = 0; i < joints.size(); ++i)
  {
    params += joints[i].params();
    dof += joints[i].dof();
  }

  BOOST_CHECK_EQUAL(params, mb.nrParams());
  BOOST_CHECK_EQUAL(dof, mb.nrDof());
}

BOOST_AUTO_TEST_CASE(JacobianConstructTest)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXYZSarm();

  Jacobian jac1(mb, "b3");
  Jacobian jac2(mb, "b4");

  // test jointsPath
  std::vector<int> jointPath1 = {0, 1, 2, 3};
  std::vector<int> jointPath2 = {0, 1, 4};

  BOOST_CHECK_EQUAL_COLLECTIONS(jointPath1.begin(), jointPath1.end(), jac1.jointsPath().begin(),
                                jac1.jointsPath().end());
  BOOST_CHECK_EQUAL_COLLECTIONS(jointPath2.begin(), jointPath2.end(), jac2.jointsPath().begin(),
                                jac2.jointsPath().end());

  // test subMultibody
  MultiBody chain1 = jac1.subMultiBody(mb);
  MultiBody chain2 = jac2.subMultiBody(mb);

  // chain 1
  std::vector<Body> bodies = {mb.body(0), mb.body(1), mb.body(2), mb.body(3)};

  std::vector<Joint> joints = {Joint(Joint::Fixed, true, "Root"), mb.joint(1), mb.joint(2), mb.joint(3)};

  std::vector<int> pred = {-1, 0, 1, 2};
  std::vector<int> succ = {0, 1, 2, 3};
  std::vector<int> parent = {-1, 0, 1, 2};

  PTransformd I(PTransformd::Identity());
  PTransformd to(Vector3d(0., 0.5, 0.));
  PTransformd unitY(Vector3d(0., 1., 0.));
  std::vector<PTransformd> Xt = {I, to, unitY, unitY};

  checkMultiBodyEq(chain1, bodies, joints, pred, succ, parent, Xt);

  // chain 2
  bodies = {mb.body(0), mb.body(1), mb.body(4)};

  joints = {Joint(Joint::Fixed, true, "Root"), mb.joint(1), mb.joint(4)};

  pred = {-1, 0, 1};
  succ = {0, 1, 2};
  parent = {-1, 0, 1};

  Xt = {I, to, PTransformd(Vector3d(0.5, 0.5, 0.))};

  checkMultiBodyEq(chain2, bodies, joints, pred, succ, parent, Xt);

  // test subMultiBody safe version
  BOOST_CHECK_THROW(jac1.sSubMultiBody(chain2), std::domain_error);
}

void checkJacobianMatrixFromVelocity(const rbd::MultiBody & subMb,
                                     rbd::MultiBodyConfig & subMbc,
                                     const std::vector<sva::MotionVecd> & velVec,
                                     const Eigen::MatrixXd & jacMat)
{
  int col = 0;
  for(int i = 0; i < subMb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < subMb.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      subMbc.alpha[ui][uj] = 1.;

      forwardVelocity(subMb, subMbc);

      Eigen::Vector6d mv = velVec.back().vector();

      BOOST_CHECK_SMALL((mv - jacMat.col(col)).norm(), TOL);

      subMbc.alpha[ui][uj] = 0.;
      ++col;
    }
  }
}

void checkJacobianMatrixSize(const rbd::MultiBody & subMb, const Eigen::MatrixXd & jacMat)
{
  // test jacobian size
  BOOST_CHECK_EQUAL(jacMat.rows(), 6);
  BOOST_CHECK_EQUAL(jacMat.cols(), subMb.nrDof());
}

void checkFullJacobianMatrix(const rbd::MultiBody & mb,
                             const rbd::MultiBody & subMb,
                             const rbd::Jacobian & jac,
                             const Eigen::MatrixXd & jacMat)
{
  using namespace Eigen;

  MatrixXd fakeFull1(5, mb.nrDof());
  MatrixXd fakeFull2(6, mb.nrDof() + 1);
  MatrixXd fullJacMat(6, mb.nrDof());
  BOOST_CHECK_THROW(jac.sFullJacobian(mb, jacMat, fakeFull1), std::domain_error);
  BOOST_CHECK_THROW(jac.sFullJacobian(mb, jacMat, fakeFull2), std::domain_error);
  BOOST_CHECK_NO_THROW(jac.sFullJacobian(mb, jacMat, fullJacMat));

  for(int i = 0; i < subMb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    int joint = jac.jointsPath()[ui];
    int dof = subMb.joint(i).dof();

    BOOST_CHECK_EQUAL(jacMat.block(0, subMb.jointPosInDof(i), 6, dof),
                      fullJacMat.block(0, mb.jointPosInDof(joint), 6, dof));
  }
}

void checkJacobian(const rbd::MultiBody & mb, const rbd::MultiBodyConfig & mbc, rbd::Jacobian & jac)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  const MatrixXd & jac_mat = jac.jacobian(mb, mbc);
  MultiBody subMb = jac.subMultiBody(mb);

  // fill subMbc
  MultiBodyConfig subMbc(subMb);
  for(size_t i = 0; i < static_cast<size_t>(subMb.nrJoints()); ++i)
  {
    const auto joint_index = static_cast<size_t>(jac.jointsPath()[i]);
    subMbc.bodyPosW[i] = mbc.bodyPosW[joint_index];
    subMbc.jointConfig[i] = mbc.jointConfig[joint_index];
    subMbc.parentToSon[i] = mbc.parentToSon[joint_index];
  }

  // test fullJacobian
  checkFullJacobianMatrix(mb, subMb, jac, jac_mat);

  // test jacobian
  const MatrixXd & jac_mat_w = jac.jacobian(mb, mbc);
  checkJacobianMatrixSize(subMb, jac_mat_w);
  checkJacobianMatrixFromVelocity(subMb, subMbc, subMbc.bodyVelW, jac_mat_w);

  // test bodyJacobian
  const MatrixXd & jac_mat_b = jac.bodyJacobian(mb, mbc);
  checkJacobianMatrixSize(subMb, jac_mat_b);
  checkJacobianMatrixFromVelocity(subMb, subMbc, subMbc.bodyVelB, jac_mat_b);
}

void checkJacobianRefBody(const rbd::MultiBody & mb, const rbd::MultiBodyConfig & mbc, rbd::Jacobian & jac)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  const MatrixXd & jac_mat = jac.jacobian(mb, mbc);
  MultiBody subMb = jac.subMultiBody(mb);

  // fill subMbc
  MultiBodyConfig subMbc(subMb);

  for(size_t i = 0; i < static_cast<size_t>(subMb.nrJoints()); ++i)
  {
    const auto joint_index = static_cast<size_t>(jac.jointsPath()[i]);
    subMbc.q[i] = mbc.q[joint_index];
  }

  forwardKinematics(subMb, subMbc);
  forwardVelocity(subMb, subMbc);

  // test fullJacobian
  checkFullJacobianMatrix(mb, subMb, jac, jac_mat);

  // test jacobian
  const MatrixXd & jac_mat_w = jac.jacobian(mb, mbc);
  checkJacobianMatrixSize(subMb, jac_mat_w);
  checkJacobianMatrixFromVelocity(subMb, subMbc, subMbc.bodyVelW, jac_mat_w);

  // test bodyJacobian
  const MatrixXd & jac_mat_b = jac.bodyJacobian(mb, mbc);
  checkJacobianMatrixSize(subMb, jac_mat_b);
  checkJacobianMatrixFromVelocity(subMb, subMbc, subMbc.bodyVelB, jac_mat_b);
}

BOOST_AUTO_TEST_CASE(JacobianComputeTest)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXYZSarm();

  Jacobian jac1(mb, "b3");
  Jacobian jac2(mb, "b4");

  mbc.q = {{}, {0.}, {0.}, {0.}, {1., 0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);
  checkJacobian(mb, mbc, jac2);

  mbc.q = {{}, {rbd::PI / 2.}, {0.}, {0.}, {1., 0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);
  checkJacobian(mb, mbc, jac2);

  // test jacobian safe version
  MultiBodyConfig mbcBadNrBodyPos(mbc);
  mbcBadNrBodyPos.bodyPosW.resize(1);
  BOOST_CHECK_THROW(jac1.sJacobian(mb, mbcBadNrBodyPos), std::domain_error);

  MultiBodyConfig mbcBadNrJointConf(mbc);
  mbcBadNrJointConf.motionSubspace.resize(1);
  BOOST_CHECK_THROW(jac1.sJacobian(mb, mbcBadNrJointConf), std::domain_error);

  MultiBody mbErr = jac2.subMultiBody(mb);
  MultiBodyConfig mbcErr(mbErr);
  BOOST_CHECK_THROW(jac1.sJacobian(mbErr, mbcErr), std::domain_error);
}

BOOST_AUTO_TEST_CASE(JacobianRefBodyTest)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXXXdualarm(false);

  Jacobian jac1(mb, "b31", "b32");
  Jacobian jac2(mb, "b32", "b31");

  Quaterniond quat(AngleAxisd(rbd::PI / 2., Vector3d::UnitX()) * AngleAxisd(rbd::PI / 8., Vector3d::UnitZ()));
  Vector3d tran = Vector3d::Random() * 10.;

  mbc.q = {{quat.w(), quat.x(), quat.y(), quat.z(), tran.x(), tran.y(), tran.z()}, {0.}, {0.}, {0.}, {0.}, {0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobianRefBody(mb, mbc, jac1);
  checkJacobianRefBody(mb, mbc, jac2);

  mbc.q = {{quat.w(), quat.x(), quat.y(), quat.z(), tran.x(), tran.y(), tran.z()},
           {rbd::PI / 2.},
           {rbd::PI / 3.},
           {rbd::PI / 4.},
           {rbd::PI / 5.},
           {rbd::PI / 6.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobianRefBody(mb, mbc, jac1);
  checkJacobianRefBody(mb, mbc, jac2);

  // test jacobian safe version
  MultiBodyConfig mbcBadNrBodyPos(mbc);
  mbcBadNrBodyPos.bodyPosW.resize(1);
  BOOST_CHECK_THROW(jac1.sJacobian(mb, mbcBadNrBodyPos), std::domain_error);

  MultiBodyConfig mbcBadNrJointConf(mbc);
  mbcBadNrJointConf.motionSubspace.resize(1);
  BOOST_CHECK_THROW(jac1.sJacobian(mb, mbcBadNrJointConf), std::domain_error);

  MultiBody mbErr = jac2.subMultiBody(mb);
  MultiBodyConfig mbcErr(mbErr);
  BOOST_CHECK_THROW(jac1.sJacobian(mbErr, mbcErr), std::domain_error);
}

BOOST_AUTO_TEST_CASE(JacobianComputeTestFreeFlyer)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXYZSarm(false);

  Jacobian jac1(mb, "b3");
  Jacobian jac2(mb, "b4");

  Quaterniond quat(AngleAxisd(rbd::PI / 2., Vector3d::UnitX()) * AngleAxisd(rbd::PI / 8., Vector3d::UnitZ()));
  Vector3d tran = Vector3d::Random() * 10.;

  mbc.q = {{quat.w(), quat.x(), quat.y(), quat.z(), tran.x(), tran.y(), tran.z()}, {0.}, {0.}, {0.}, {1., 0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);
  checkJacobian(mb, mbc, jac2);

  quat = (AngleAxisd(rbd::PI / 8., Vector3d::UnitX()) * AngleAxisd(rbd::PI / 2., Vector3d::UnitZ()));
  tran = Vector3d::Random() * 10.;
  mbc.q = {{quat.w(), quat.x(), quat.y(), quat.z(), tran.x(), tran.y(), tran.z()},
           {rbd::PI / 2.},
           {0.},
           {0.},
           {1., 0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);
  checkJacobian(mb, mbc, jac2);

  // test jacobian safe version
  MultiBodyConfig mbcBadNrBodyPos(mbc);
  mbcBadNrBodyPos.bodyPosW.resize(1);
  BOOST_CHECK_THROW(jac1.sJacobian(mb, mbcBadNrBodyPos), std::domain_error);

  MultiBodyConfig mbcBadNrJointConf(mbc);
  mbcBadNrJointConf.motionSubspace.resize(1);
  BOOST_CHECK_THROW(jac1.sJacobian(mb, mbcBadNrJointConf), std::domain_error);

  MultiBody mbErr = jac2.subMultiBody(mb);
  MultiBodyConfig mbcErr(mbErr);
  BOOST_CHECK_THROW(jac1.sJacobian(mbErr, mbcErr), std::domain_error);
}

BOOST_AUTO_TEST_CASE(JacobianComputeTest2)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeSSSarm(true);

  Jacobian jac1(mb, "b3");

  mbc.q = {{}, {1., 0., 0., 0.}, {1., 0., 0., 0.}, {1., 0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);

  Quaterniond q1(AngleAxisd(rbd::PI / 2., Vector3d::UnitX()));
  Quaterniond q2 = Quaterniond::Identity();
  Quaterniond q3 = Quaterniond::Identity();
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);

  q1 = AngleAxisd(rbd::PI / 2., Vector3d::UnitX()) * AngleAxisd(rbd::PI / 4., Vector3d::UnitY());
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);

  q2 = AngleAxisd(rbd::PI / 4., Vector3d::UnitX());
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);

  q3 = AngleAxisd(rbd::PI / 8., Vector3d::UnitZ());
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  checkJacobian(mb, mbc, jac1);
}

typedef std::function<const Eigen::MatrixXd &(const rbd::MultiBody &, const rbd::MultiBodyConfig &)> jacobianComputeFunc;

Eigen::MatrixXd makeJDotFromStep(const rbd::MultiBody & mb,
                                 const rbd::MultiBodyConfig & mbc,
                                 jacobianComputeFunc jacComp)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  double step = 1e-8;

  MultiBodyConfig mbcTmp(mbc);

  MatrixXd oJ = jacComp(mb, mbcTmp);
  integration(mb, mbcTmp, step);
  forwardKinematics(mb, mbcTmp);
  forwardVelocity(mb, mbcTmp);
  MatrixXd nJ = jacComp(mb, mbcTmp);

  return (nJ - oJ) / step;
}

typedef const Eigen::MatrixXd & (rbd::Jacobian::*worldJacobian_t)(const rbd::MultiBody &, const rbd::MultiBodyConfig &);
typedef sva::MotionVecd (rbd::Jacobian::*worldVelocity_t)(const rbd::MultiBody &, const rbd::MultiBodyConfig &) const;

void testJacobianDot(const rbd::MultiBody & mb, const rbd::MultiBodyConfig & mbc, rbd::Jacobian & jac)
{
  using namespace std::placeholders; // bind
  using namespace Eigen;

  MatrixXd JD_diff = makeJDotFromStep(mb, mbc, std::bind(worldJacobian_t(&rbd::Jacobian::jacobian), jac, _1, _2));
  MatrixXd JD = jac.jacobianDot(mb, mbc);

  BOOST_CHECK_SMALL((JD_diff - JD).norm(), 2e-5);

  MatrixXd JD_diff_b = makeJDotFromStep(mb, mbc, std::bind(&rbd::Jacobian::bodyJacobian, jac, _1, _2));
  MatrixXd JD_b = jac.bodyJacobianDot(mb, mbc);

  BOOST_CHECK_SMALL((JD_diff_b - JD_b).norm(), 2e-5);
}

BOOST_AUTO_TEST_CASE(JacobianDotComputeTest)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeSSSarm(true);

  Jacobian jac1(mb, "b3");

  mbc.q = {{}, {1., 0., 0., 0.}, {1., 0., 0., 0.}, {1., 0., 0., 0.}};
  mbc.alpha = {{}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};
  mbc.alphaD = {{}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};
  forwardKinematics(mb, mbc);
  for(int i = 0; i < mb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mb.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbc.alpha[ui][uj] = 1.;
      forwardVelocity(mb, mbc);

      testJacobianDot(mb, mbc, jac1);

      mbc.alpha[ui][uj] = 0.;
    }
  }

  Quaterniond q1 = AngleAxisd(rbd::PI / 2., Vector3d::UnitX()) * AngleAxisd(rbd::PI / 4., Vector3d::UnitY());
  Quaterniond q2 = Quaterniond::Identity();
  Quaterniond q3 = Quaterniond::Identity();
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mb, mbc);
  for(int i = 0; i < mb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mb.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbc.alpha[ui][uj] = 1.;
      forwardVelocity(mb, mbc);

      testJacobianDot(mb, mbc, jac1);

      mbc.alpha[ui][uj] = 0.;
    }
  }

  q2 = AngleAxisd(rbd::PI / 4., Vector3d::UnitX());
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mb, mbc);
  for(int i = 0; i < mb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mb.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbc.alpha[ui][uj] = 1.;
      forwardVelocity(mb, mbc);

      testJacobianDot(mb, mbc, jac1);

      mbc.alpha[ui][uj] = 0.;
    }
  }

  q3 = AngleAxisd(rbd::PI / 8., Vector3d::UnitZ());
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mb, mbc);
  for(int i = 0; i < mb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mb.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbc.alpha[ui][uj] = 1.;
      forwardVelocity(mb, mbc);

      testJacobianDot(mb, mbc, jac1);

      mbc.alpha[ui][uj] = 0.;
    }
  }

  // test with all joint velocity
  for(int i = 0; i < mb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mb.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbc.alpha[ui][uj] = 1.;
      forwardVelocity(mb, mbc);

      testJacobianDot(mb, mbc, jac1);
    }
  }
  mbc.alpha = {{}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};

  // test with a point
  Jacobian jacP(mb, "b3", Vector3d::Random() * 10.);
  for(int i = 0; i < mb.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mb.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbc.alpha[ui][uj] = 1.;
      forwardVelocity(mb, mbc);

      testJacobianDot(mb, mbc, jacP);
    }
  }
  mbc.alpha = {{}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};

  // test with free flyier

  MultiBody mbF = mbg.makeMultiBody("b0", false);

  MultiBodyConfig mbcF(mbF);

  Jacobian jacF(mbF, "b3");

  mbcF.q = {{1., 0., 0., 0., 0., 0., 0.}, {1., 0., 0., 0.}, {1., 0., 0., 0.}, {1., 0., 0., 0.}};
  mbcF.alpha = {{0., 0., 0., 0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};
  mbcF.alphaD = {{0., 0., 0., 0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};
  forwardKinematics(mbF, mbcF);

  for(int i = 0; i < mbF.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mbF.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbcF.alpha[ui][uj] = 1.;
      forwardVelocity(mbF, mbcF);

      testJacobianDot(mbF, mbcF, jacF);
    }
  }
  mbcF.alpha = {{0., 0., 0., 0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};

  Quaterniond qF = AngleAxisd(1.2, Vector3d::UnitX()) * AngleAxisd(-0.4, Vector3d::UnitZ());
  mbc.q = {{qF.w(), qF.x(), qF.y(), qF.z(), 1., 2., 3.},
           {q1.w(), q1.x(), q1.y(), q1.z()},
           {q2.w(), q2.x(), q2.y(), q2.z()},
           {q3.w(), q3.x(), q3.y(), q3.z()}};
  forwardKinematics(mbF, mbcF);

  for(int i = 0; i < mbF.nrJoints(); ++i)
  {
    const auto ui = static_cast<size_t>(i);
    for(int j = 0; j < mbF.joint(i).dof(); ++j)
    {
      const auto uj = static_cast<size_t>(j);
      mbcF.alpha[ui][uj] = 1.;
      forwardVelocity(mbF, mbcF);

      testJacobianDot(mbF, mbcF, jacF);
    }
  }
  mbcF.alpha = {{0., 0., 0., 0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};
}

void testTranslateJacobian(const rbd::MultiBody & mb,
                           const rbd::MultiBodyConfig & mbc,
                           const Eigen::Vector3d & P,
                           rbd::Jacobian & jacO,
                           rbd::Jacobian & jacP)
{
  using namespace Eigen;

  MatrixXd JO_w = jacO.jacobian(mb, mbc);
  MatrixXd JP_w = jacP.jacobian(mb, mbc);

  MatrixXd JO_P_w = JO_w;
  jacO.translateJacobian(JO_w, mbc, P, JO_P_w);

  BOOST_CHECK_SMALL((JO_P_w - JP_w).norm(), TOL);

  MatrixXd JO_b = jacO.jacobian(mb, mbc);
  MatrixXd JP_b = jacP.jacobian(mb, mbc);

  MatrixXd JO_P_b = JO_b;
  jacO.translateJacobian(JO_b, mbc, P, JO_P_b);

  BOOST_CHECK_SMALL((JO_P_b - JP_b).norm(), TOL);
}

BOOST_AUTO_TEST_CASE(JacobianTranslateTest)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeSSSarm(true);

  Vector3d point = Vector3d::Random() * 10.;

  Jacobian jacO(mb, "b3");
  Jacobian jacP(mb, "b3", point);

  mbc.q = {{}, {1., 0., 0., 0.}, {1., 0., 0., 0.}, {1., 0., 0., 0.}};
  mbc.alpha = {{}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};
  mbc.alphaD = {{}, {0., 0., 0.}, {0., 0., 0.}, {0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  testTranslateJacobian(mb, mbc, point, jacO, jacP);

  Quaterniond q1 = AngleAxisd(rbd::PI / 2., Vector3d::UnitX()) * AngleAxisd(rbd::PI / 4., Vector3d::UnitY());
  Quaterniond q2(AngleAxisd(rbd::PI / 4., Vector3d::UnitX()));
  Quaterniond q3(AngleAxisd(rbd::PI / 8., Vector3d::UnitZ()));
  mbc.q = {{}, {q1.w(), q1.x(), q1.y(), q1.z()}, {q2.w(), q2.x(), q2.y(), q2.z()}, {q3.w(), q3.x(), q3.y(), q3.z()}};

  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  testTranslateJacobian(mb, mbc, point, jacO, jacP);
}

Eigen::MatrixXd jacobianVecBodyFromJac(const rbd::MultiBody & mb,
                                       const rbd::MultiBodyConfig & mbc,
                                       rbd::Jacobian & jac,
                                       const Eigen::Vector3d & vec)
{
  Eigen::MatrixXd jacO = jac.bodyJacobian(mb, mbc);
  Eigen::MatrixXd jacV(jacO.rows(), jacO.cols());
  jac.translateBodyJacobian(jacO, mbc, vec, jacV);

  return jacV - jacO;
}

Eigen::MatrixXd jacobianVecFromJac(const rbd::MultiBody & mb,
                                   const rbd::MultiBodyConfig & mbc,
                                   rbd::Jacobian & jac,
                                   const Eigen::Vector3d & vec)
{
  Eigen::MatrixXd jacO = jac.jacobian(mb, mbc);
  Eigen::MatrixXd jacV(jacO.rows(), jacO.cols());
  jac.translateJacobian(jacO, mbc, vec, jacV);

  return jacV - jacO;
}

BOOST_AUTO_TEST_CASE(JacobianVectorTest)
{
  rbd::MultiBody mb;
  rbd::MultiBodyConfig mbc;
  rbd::MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXYZSarm(false);

  rbd::forwardKinematics(mb, mbc);
  rbd::forwardVelocity(mb, mbc);

  rbd::Jacobian jac1(mb, "b3");
  rbd::Jacobian jac2(mb, "b4", Eigen::Vector3d(0.1, -0.1, 0.2));

  for(int i = 0; i < 50; ++i)
  {
    Eigen::VectorXd q(mb.nrParams());
    q.setRandom();
    // normalize free flyier and spherical joint
    q.head<4>().normalize();
    q.segment(mb.jointPosInParam(mb.jointIndexByName("j3")), 4).normalize();
    rbd::vectorToParam(q, mbc.q);
    forwardKinematics(mb, mbc);

    Eigen::Vector3d vec;
    vec.setRandom();

    // vectorBody
    Eigen::MatrixXd jac1MatDiff = jacobianVecBodyFromJac(mb, mbc, jac1, vec);
    Eigen::MatrixXd jac1Mat = jac1.vectorBodyJacobian(mb, mbc, vec);

    BOOST_CHECK_SMALL((jac1MatDiff.block(3, 0, 3, jac1.dof()) - jac1Mat.block(3, 0, 3, jac1.dof())).norm(), TOL);

    Eigen::MatrixXd jac2MatDiff = jacobianVecBodyFromJac(mb, mbc, jac2, vec);
    Eigen::MatrixXd jac2Mat = jac2.vectorBodyJacobian(mb, mbc, vec);

    BOOST_CHECK_SMALL((jac2MatDiff.block(3, 0, 3, jac2.dof()) - jac2Mat.block(3, 0, 3, jac2.dof())).norm(), TOL);

    // vector
    Eigen::MatrixXd jac3MatDiff = jacobianVecFromJac(mb, mbc, jac1, vec);
    Eigen::MatrixXd jac3Mat = jac1.vectorJacobian(mb, mbc, vec);

    BOOST_CHECK_SMALL((jac3MatDiff.block(3, 0, 3, jac1.dof()) - jac3Mat.block(3, 0, 3, jac1.dof())).norm(), TOL);

    Eigen::MatrixXd jac4MatDiff = jacobianVecFromJac(mb, mbc, jac2, vec);
    Eigen::MatrixXd jac4Mat = jac2.vectorJacobian(mb, mbc, vec);

    BOOST_CHECK_SMALL((jac4MatDiff.block(3, 0, 3, jac2.dof()) - jac4Mat.block(3, 0, 3, jac2.dof())).norm(), TOL);
  }
}

template<typename MatFunc, typename VectorFunc>
Eigen::Vector6d testMatrixAgainstVector(const rbd::MultiBody & mb,
                                        const rbd::MultiBodyConfig & mbc,
                                        const rbd::Jacobian & jac,
                                        MatFunc && matFunc,
                                        const Eigen::VectorXd & alpha,
                                        VectorFunc && vectorFunc)
{
  const Eigen::MatrixXd & mat = std::forward<MatFunc>(matFunc)(mb, mbc);
  Eigen::MatrixXd matFull(6, mb.nrDof());
  jac.fullJacobian(mb, mat, matFull);
  Eigen::Vector6d res = matFull * alpha;
  sva::MotionVecd mv = std::forward<VectorFunc>(vectorFunc)(mb, mbc);

  return mv.vector() - res;
}

BOOST_AUTO_TEST_CASE(JacobianVectorVelAccComputeTest)
{
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;
  using namespace std::placeholders;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXYZSarm(false);

  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  Jacobian jac1(mb, "b3");
  Jacobian jac2(mb, "b4");

  for(int i = 0; i < 50; ++i)
  {
    Eigen::VectorXd q(mb.nrParams()), alpha(mb.nrDof());
    q.setRandom();
    alpha.setRandom();
    // normalize free flyier and spherical joint
    q.head<4>().normalize();
    q.segment(mb.jointPosInParam(mb.jointIndexByName("j3")), 4).normalize();
    rbd::vectorToParam(q, mbc.q);
    rbd::vectorToParam(alpha, mbc.alpha);
    forwardKinematics(mb, mbc);
    forwardVelocity(mb, mbc);
    // calcul the normal acceleration since alphaD is zero
    forwardAcceleration(mb, mbc);

    Vector3d point(Vector3d::Random());
    for(Jacobian & jac : {std::ref(jac1), std::ref(jac2)})
    {
      jac.point(point);

      BOOST_CHECK_SMALL(
          testMatrixAgainstVector(mb, mbc, jac, std::bind(worldJacobian_t(&Jacobian::jacobian), std::ref(jac), _1, _2),
                                  alpha, std::bind(worldVelocity_t(&Jacobian::velocity), std::ref(jac), _1, _2))
              .norm(),
          TOL);

      BOOST_CHECK_SMALL(testMatrixAgainstVector(mb, mbc, jac, std::bind(&Jacobian::bodyJacobian, std::ref(jac), _1, _2),
                                                alpha, std::bind(&Jacobian::bodyVelocity, std::ref(jac), _1, _2))
                            .norm(),
                        TOL);

      typedef MotionVecd (Jacobian::*normalAccel_func1)(const MultiBody &, const MultiBodyConfig &) const;
      typedef MotionVecd (Jacobian::*normalAccel_func2)(const MultiBody &, const MultiBodyConfig &,
                                                        const std::vector<sva::MotionVecd> &) const;

      BOOST_CHECK_SMALL(testMatrixAgainstVector(mb, mbc, jac, std::bind(&Jacobian::jacobianDot, std::ref(jac), _1, _2),
                                                alpha,
                                                std::bind(static_cast<normalAccel_func1>(&Jacobian::normalAcceleration),
                                                          std::ref(jac), _1, _2))
                            .norm(),
                        TOL);

      BOOST_CHECK_SMALL(
          testMatrixAgainstVector(
              mb, mbc, jac, std::bind(&Jacobian::bodyJacobianDot, std::ref(jac), _1, _2), alpha,
              std::bind(static_cast<normalAccel_func1>(&Jacobian::bodyNormalAcceleration), std::ref(jac), _1, _2))
              .norm(),
          TOL);

      BOOST_CHECK_SMALL(testMatrixAgainstVector(mb, mbc, jac, std::bind(&Jacobian::jacobianDot, std::ref(jac), _1, _2),
                                                alpha,
                                                std::bind(static_cast<normalAccel_func2>(&Jacobian::normalAcceleration),
                                                          std::ref(jac), _1, _2, std::ref(mbc.bodyAccB)))
                            .norm(),
                        TOL);

      BOOST_CHECK_SMALL(
          testMatrixAgainstVector(mb, mbc, jac, std::bind(&Jacobian::bodyJacobianDot, std::ref(jac), _1, _2), alpha,
                                  std::bind(static_cast<normalAccel_func2>(&Jacobian::bodyNormalAcceleration),
                                            std::ref(jac), _1, _2, std::ref(mbc.bodyAccB)))
              .norm(),
          TOL);

      // The caller-supplied-frame overloads velocity(X_b_p) and
      // normalAcceleration(X_b_p, V_b_p) are part of the public surface too. Check
      // them through relations that hold whatever frame X_b_p is taken to map from,
      // so nothing here depends on the frame the no-argument overloads pick.
      const Quaterniond E1q = AngleAxisd(0.37, Vector3d::UnitZ()) * AngleAxisd(-0.81, Vector3d::UnitY());
      const Quaterniond E2q = AngleAxisd(-0.53, Vector3d::UnitX()) * AngleAxisd(0.22, Vector3d::UnitZ());
      const Matrix3d E1 = E1q.toRotationMatrix();
      const Matrix3d E2 = E2q.toRotationMatrix();
      const PTransformd X1(E1, Vector3d::Random());
      const PTransformd X2(E2, Vector3d::Random());

      // X_b_p acts on the returned motion vector, so the overload is covariant
      // under composition of frames: velocity(X2 * X1) == X2 * velocity(X1).
      const MotionVecd vel_X1 = jac.velocity(mb, mbc, X1);
      const MotionVecd vel_X2X1 = jac.velocity(mb, mbc, X2 * X1);
      BOOST_CHECK_SMALL((vel_X2X1.vector() - (X2 * vel_X1).vector()).norm(), TOL);

      // The normalAccB overloads use the caller-supplied normal accelerations instead
      // of recomputing them, so feeding back the recomputed ones (mbc.bodyAccB, with
      // alphaD == 0) must reproduce the recomputing overload at the same (X_b_p, V_b_p).
      typedef MotionVecd (Jacobian::*normalAccel_Xbp_1)(const MultiBody &, const MultiBodyConfig &,
                                                        const sva::PTransformd &, const sva::MotionVecd &) const;
      typedef MotionVecd (Jacobian::*normalAccel_Xbp_2)(const MultiBody &, const MultiBodyConfig &,
                                                        const std::vector<sva::MotionVecd> &, const sva::PTransformd &,
                                                        const sva::MotionVecd &) const;

      const MotionVecd V_b_p(Vector3d::Random(), Vector3d::Random());
      const MotionVecd nA_recomputed =
          (jac.*static_cast<normalAccel_Xbp_1>(&Jacobian::normalAcceleration))(mb, mbc, X1, V_b_p);
      const MotionVecd nA_supplied =
          (jac.*static_cast<normalAccel_Xbp_2>(&Jacobian::normalAcceleration))(mb, mbc, mbc.bodyAccB, X1, V_b_p);
      BOOST_CHECK_SMALL((nA_recomputed.vector() - nA_supplied.vector()).norm(), TOL);
    }
  }
}

BOOST_AUTO_TEST_CASE(JacobianXbpTest)
{
  // Exercises the 3-arg jacobian(mb, mbc, X_0_p) overload.
  //
  // Upstream Jacobian.cpp semantics:
  //  * The 2-arg jacobian(mb, mbc) internally builds
  //      T_0_Np = (point_ * bodyPosW[N]).translation()   (translation only)
  //    and passes a translation-only PTransformd to the inner jacobian_ helper.
  //  * The 3-arg jacobian(mb, mbc, X_0_p) passes X_0_p verbatim (rotation +
  //    translation) to the same helper.
  //  * bodyJacobian(mb, mbc) internally builds
  //      X_0_Np = point_ * bodyPosW[N]                   (rotation + translation)
  //    and passes the full PTransformd to the helper.
  //
  // So we can pin both semantics with two equivalences, plus a third check at an
  // arbitrary X_0_p that matches neither special shape.
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXYZSarm();

  mbc.q = {{}, {rbd::PI / 2.}, {rbd::PI / 3.}, {rbd::PI / 4.}, {1., 0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  const Vector3d body_offset(0.1, 0.2, 0.3);
  Jacobian jac_at_offset(mb, "b3", body_offset);
  const int b3_idx = mb.bodyIndexByName("b3");
  const auto b3_u = static_cast<size_t>(b3_idx);

  const double TOL_TIGHT = 1e-10;

  // (a) Full-PTransformd X_0_p equivalence: matches bodyJacobian
  //     X_0_p_full = point_offset * bodyPosW[b3]  (rotation + translation)
  {
    const PTransformd X_0_p_full = PTransformd(body_offset) * mbc.bodyPosW[b3_u];
    const MatrixXd jac_via_full_Xbp = jac_at_offset.jacobian(mb, mbc, X_0_p_full);
    const MatrixXd jac_via_body     = jac_at_offset.bodyJacobian(mb, mbc);
    BOOST_CHECK_SMALL((jac_via_full_Xbp - jac_via_body).norm(), TOL_TIGHT);
  }

  // (b) Translation-only X_0_p equivalence: matches 2-arg jacobian
  //     X_0_p_trans = PT(translation only, from point_offset * bodyPosW[b3])
  {
    const PTransformd X_0_p_trans(
        (PTransformd(body_offset) * mbc.bodyPosW[b3_u]).translation());
    const MatrixXd jac_via_trans_Xbp = jac_at_offset.jacobian(mb, mbc, X_0_p_trans);
    const MatrixXd jac_via_2arg      = jac_at_offset.jacobian(mb, mbc);
    BOOST_CHECK_SMALL((jac_via_trans_Xbp - jac_via_2arg).norm(), TOL_TIGHT);
  }

  // (c) Arbitrary X_0_p: the rows are the same motions read in the frame X_0_p, so
  //     re-expressing them in a further frame X_p_q must transform every column by
  //     X_p_q. Neither X_0_p nor X_p_q * X_0_p is world- or body-oriented here, so a
  //     general implementation is required (delegating to the two overloads above
  //     cannot satisfy this).
  {
    const Quaterniond Epq = AngleAxisd(-0.45, Vector3d::UnitZ()) * AngleAxisd(0.13, Vector3d::UnitY());
    const PTransformd X_0_p_arb(
        Matrix3d(Quaterniond(AngleAxisd(0.61, Vector3d::UnitY()) * AngleAxisd(-0.29, Vector3d::UnitX()))
                     .toRotationMatrix()),
        Vector3d(0.4, -0.2, 0.9));
    const PTransformd X_p_q(Matrix3d(Epq.toRotationMatrix()), Vector3d(-0.7, 0.3, 0.15));

    const MatrixXd jac_in_p = jac_at_offset.jacobian(mb, mbc, X_0_p_arb);
    const MatrixXd jac_in_q = jac_at_offset.jacobian(mb, mbc, X_p_q * X_0_p_arb);

    MatrixXd jac_p_moved_to_q(jac_in_p.rows(), jac_in_p.cols());
    for(Eigen::DenseIndex c = 0; c < jac_in_p.cols(); ++c)
    {
      jac_p_moved_to_q.col(c) = (X_p_q * MotionVecd(Vector6d(jac_in_p.col(c)))).vector();
    }
    BOOST_CHECK_SMALL((jac_in_q - jac_p_moved_to_q).norm(), TOL_TIGHT);
  }
}

BOOST_AUTO_TEST_CASE(JacobianSXxxxThrowTest)
{
  // Parametric throw check over the sXxxx safe variants of Jacobian.
  // Each variant is required to throw std::domain_error before delegating
  // to the unchecked implementation when its mbc or shape preconditions
  // are violated.
  using namespace Eigen;
  using namespace sva;
  using namespace rbd;

  MultiBody mb;
  MultiBodyConfig mbc;
  MultiBodyGraph mbg;
  std::tie(mb, mbc, mbg) = makeXYZSarm();

  mbc.q = {{}, {0.}, {0.}, {0.}, {1., 0., 0., 0.}};
  forwardKinematics(mb, mbc);
  forwardVelocity(mb, mbc);

  Jacobian jac(mb, "b3");
  const PTransformd X_0_p_dummy = PTransformd::Identity();
  const Vector3d vec_dummy = Vector3d::Zero();
  const Vector3d point_dummy = Vector3d::Zero();

  // Group 1 — mbc.bodyPosW.resize(1) trips checkMatchBodyPos.
  // These sXxxx call checkMatchBodyPos as their first guard:
  //   sJacobian, sBodyJacobian, sVectorJacobian, sVectorBodyJacobian,
  //   sJacobianDot, sBodyJacobianDot, sVelocity, sNormalAcceleration.
  {
    MultiBodyConfig mbcBad(mbc);
    mbcBad.bodyPosW.resize(1);
    BOOST_CHECK_THROW(jac.sJacobian(mb, mbcBad, X_0_p_dummy), std::domain_error);
    BOOST_CHECK_THROW(jac.sJacobian(mb, mbcBad), std::domain_error);
    BOOST_CHECK_THROW(jac.sBodyJacobian(mb, mbcBad), std::domain_error);
    BOOST_CHECK_THROW(jac.sVectorJacobian(mb, mbcBad, vec_dummy), std::domain_error);
    BOOST_CHECK_THROW(jac.sVectorBodyJacobian(mb, mbcBad, vec_dummy), std::domain_error);
    BOOST_CHECK_THROW(jac.sJacobianDot(mb, mbcBad), std::domain_error);
    BOOST_CHECK_THROW(jac.sBodyJacobianDot(mb, mbcBad), std::domain_error);
    BOOST_CHECK_THROW(jac.sVelocity(mb, mbcBad), std::domain_error);
    BOOST_CHECK_THROW(jac.sNormalAcceleration(mb, mbcBad), std::domain_error);
  }

  // Group 2 — mbc.bodyVelB.resize(1) trips checkMatchBodyVel (used by sBodyVelocity).
  {
    MultiBodyConfig mbcBad(mbc);
    mbcBad.bodyVelB.resize(1);
    BOOST_CHECK_THROW(jac.sBodyVelocity(mb, mbcBad), std::domain_error);
  }

  // Group 3 — mbc.parentToSon.resize(1) trips checkMatchParentToSon
  // (used by sBodyNormalAcceleration).
  {
    MultiBodyConfig mbcBad(mbc);
    mbcBad.parentToSon.resize(1);
    BOOST_CHECK_THROW(jac.sBodyNormalAcceleration(mb, mbcBad), std::domain_error);
  }

  // Group 4 — sSubMultiBody with a MB that doesn't contain jac's jointsPath.
  // jac (for b3) has jointsPath {0,1,2,3}; sub_b4 (for b4) has 3 joints
  // (indices 0..2 in the sub) so max(jac.jointsPath) >= subMb.nrJoints() → throws.
  {
    Jacobian jac_b4(mb, "b4");
    MultiBody subMb = jac_b4.subMultiBody(mb);
    BOOST_CHECK_THROW(jac.sSubMultiBody(subMb), std::domain_error);
  }

  // Group 5 — sFullJacobian with wrong-shape res (should be 6 x mb.nrDof()).
  {
    const MatrixXd jac_ok = jac.jacobian(mb, mbc);
    MatrixXd bad_res(5, mb.nrDof());
    BOOST_CHECK_THROW(jac.sFullJacobian(mb, jac_ok, bad_res), std::domain_error);
  }

  // Group 6 — sTranslateJacobian with wrong-shape jac (should be 6 x jac.dof()).
  {
    MatrixXd bad_jac(3, jac.dof());
    MatrixXd res_ok(6, jac.dof());
    BOOST_CHECK_THROW(jac.sTranslateJacobian(bad_jac, mbc, point_dummy, res_ok), std::domain_error);
  }
}
