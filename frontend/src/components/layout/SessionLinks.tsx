import Link from "next/link";

/** Account links in the public header. They are static: the session is only checked inside the
 * workspace, which sends anyone signed out to the sign-in page. */
export function SessionLinks() {
  return (
    <>
      <Link href="/login" className="site-header__link">
        Sign in
      </Link>
      <Link href="/research" className="button button--small">
        Start a review
      </Link>
    </>
  );
}
